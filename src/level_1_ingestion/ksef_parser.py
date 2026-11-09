"""
Parser faktur KSeF XML (zgodny ze schematami FA(2) oraz FA(1)).
Deterministyczny, bezstratny, z przeliczaniem kwot za pomocą Decimal.
"""

from decimal import Decimal, InvalidOperation
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Tuple
import re

from src.core.invoice import Invoice, InvoiceItem, InvoiceParty, InvoiceType


class KSeFParser:
    """
    Parser wyciągający dane ze standardowego pliku XML KSeF.
    """

    @staticmethod
    def _strip_ns(tag: str) -> str:
        """Usuwa przestrzeń nazw XML (np. {http://...}Faktura -> Faktura)."""
        return tag.split("}")[-1] if "}" in tag else tag

    @classmethod
    def _find_text(cls, element: Optional[ET.Element], path: str, default: str = "") -> str:
        if element is None:
            return default
        # Proste wyszukiwanie bez względu na namespace
        parts = path.split("/")
        curr = [element]
        for part in parts:
            next_curr = []
            for node in curr:
                for child in node:
                    if cls._strip_ns(child.tag) == part:
                        next_curr.append(child)
            curr = next_curr
            if not curr:
                return default
        if curr and curr[0].text:
            return curr[0].text.strip()
        return default

    @classmethod
    def _to_decimal(cls, val: str, default: str = "0.00") -> Decimal:
        if not val:
            return Decimal(default)
        clean = val.strip().replace(",", ".")
        try:
            return Decimal(clean)
        except InvalidOperation:
            return Decimal(default)

    @classmethod
    def parse_xml(cls, xml_content: str, target_company_nip: Optional[str] = None) -> Invoice:
        """
        Parsuje zawartość XML faktury KSeF do modelu Invoice.
        Jeśli podano target_company_nip, automatycznie określa typ (SPRZEDAZ / KOSZT).
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Błąd parsowania pliku XML KSeF: {e}")

        # Znajdź sekcje
        podmiot1_elem = None
        podmiot2_elem = None
        fa_elem = None
        wiersze_elems = []

        for child in root:
            tag = cls._strip_ns(child.tag)
            if tag == "Podmiot1":
                podmiot1_elem = child
            elif tag == "Podmiot2":
                podmiot2_elem = child
            elif tag == "Fa":
                fa_elem = child
                # Wewnątrz Fa mogą być FaWiersz
                for sub in child:
                    if cls._strip_ns(sub.tag) == "FaWiersz":
                        wiersze_elems.append(sub)

        # 1. Sprzedawca (Podmiot1)
        nip_sprzedawcy = cls._find_text(podmiot1_elem, "DaneIdentyfikacyjne/NIP")
        nazwa_sprzedawcy = (
            cls._find_text(podmiot1_elem, "DaneIdentyfikacyjne/Nazwa")
            or cls._find_text(podmiot1_elem, "DaneIdentyfikacyjne/PelnaNazwa")
            or cls._find_text(podmiot1_elem, "DaneIdentyfikacyjne/NazwaPierwsza")
        )
        sprzedawca = InvoiceParty(nip=nip_sprzedawcy, nazwa=nazwa_sprzedawcy)

        # 2. Nabywca (Podmiot2)
        nip_nabywcy = cls._find_text(podmiot2_elem, "DaneIdentyfikacyjne/NIP")
        nazwa_nabywcy = (
            cls._find_text(podmiot2_elem, "DaneIdentyfikacyjne/Nazwa")
            or cls._find_text(podmiot2_elem, "DaneIdentyfikacyjne/PelnaNazwa")
            or cls._find_text(podmiot2_elem, "DaneIdentyfikacyjne/NazwaPierwsza")
        )
        nabywca = InvoiceParty(nip=nip_nabywcy, nazwa=nazwa_nabywcy)

        # 3. Nagłówek faktury (Fa)
        numer_faktury = cls._find_text(fa_elem, "P_2")
        data_wystawienia = cls._find_text(fa_elem, "P_1")
        data_sprzedazy = cls._find_text(fa_elem, "P_6") or data_wystawienia
        waluta = cls._find_text(fa_elem, "KodWaluty", "PLN")

        suma_brutto = cls._to_decimal(cls._find_text(fa_elem, "P_15"))

        # Rozbicie stawek VAT z sekcji Fa
        stawki_netto: Dict[str, Decimal] = {}
        stawki_vat: Dict[str, Decimal] = {}

        # 23%
        p_13_1 = cls._to_decimal(cls._find_text(fa_elem, "P_13_1"))
        p_14_1 = cls._to_decimal(cls._find_text(fa_elem, "P_14_1"))
        if p_13_1 > 0 or p_14_1 > 0:
            stawki_netto["23"] = p_13_1
            stawki_vat["23"] = p_14_1

        # 8%
        p_13_2 = cls._to_decimal(cls._find_text(fa_elem, "P_13_2"))
        p_14_2 = cls._to_decimal(cls._find_text(fa_elem, "P_14_2"))
        if p_13_2 > 0 or p_14_2 > 0:
            stawki_netto["8"] = p_13_2
            stawki_vat["8"] = p_14_2

        # 5%
        p_13_3 = cls._to_decimal(cls._find_text(fa_elem, "P_13_3"))
        p_14_3 = cls._to_decimal(cls._find_text(fa_elem, "P_14_3"))
        if p_13_3 > 0 or p_14_3 > 0:
            stawki_netto["5"] = p_13_3
            stawki_vat["5"] = p_14_3

        # 0% / Zwolnione
        p_13_7 = cls._to_decimal(cls._find_text(fa_elem, "P_13_7"))
        if p_13_7 > 0:
            stawki_netto["0"] = p_13_7
            stawki_vat["0"] = Decimal("0.00")

        p_13_6_1 = cls._to_decimal(cls._find_text(fa_elem, "P_13_6_1"))
        if p_13_6_1 > 0:
            stawki_netto["zw"] = p_13_6_1
            stawki_vat["zw"] = Decimal("0.00")

        suma_netto = sum(stawki_netto.values(), Decimal("0.00"))
        suma_vat = sum(stawki_vat.values(), Decimal("0.00"))

        # Jeśli w polach szczegółowych brak sum, a P_15 jest podane:
        if suma_netto == Decimal("0.00") and suma_brutto > Decimal("0.00"):
            # Przypadek faktury uproszczonej lub zwolnionej
            suma_netto = suma_brutto

        # 4. Pozycje faktury (FaWiersz)
        pozycje = []
        for wiersz in wiersze_elems:
            nazwa_towaru = cls._find_text(wiersz, "P_7")
            ilosc = cls._to_decimal(cls._find_text(wiersz, "P_8B", "1"))
            jm = cls._find_text(wiersz, "P_8A", "szt")
            cena_netto = cls._to_decimal(cls._find_text(wiersz, "P_9A"))
            wartosc_netto = cls._to_decimal(cls._find_text(wiersz, "P_11"))
            stawka_v = cls._find_text(wiersz, "P_12", "23")
            
            # Obliczenie brutto i vat pozycji
            kwota_vat_pos = Decimal("0.00")
            if stawka_v in ["23", "8", "5"]:
                rate = Decimal(stawka_v) / Decimal("100")
                kwota_vat_pos = (wartosc_netto * rate).quantize(Decimal("0.01"))
            wartosc_brutto_pos = wartosc_netto + kwota_vat_pos

            pozycje.append(InvoiceItem(
                opis=nazwa_towaru,
                ilosc=ilosc,
                jednostka=jm,
                cena_jednostkowa_netto=cena_netto,
                wartosc_netto=wartosc_netto,
                stawka_vat=stawka_v,
                kwota_vat=kwota_vat_pos,
                wartosc_brutto=wartosc_brutto_pos,
            ))

        # 5. Określenie typu (sprzedaż czy koszt)
        typ = InvoiceType.SPRZEDAZ
        if target_company_nip:
            clean_target_nip = re.sub(r"[^0-9]", "", target_company_nip)
            if nabywca.nip == clean_target_nip:
                typ = InvoiceType.KOSZT
            elif sprzedawca.nip == clean_target_nip:
                typ = InvoiceType.SPRZEDAZ

        return Invoice(
            numer=numer_faktury,
            data_wystawienia=data_wystawienia,
            data_sprzedazy=data_sprzedazy,
            sprzedawca=sprzedawca,
            nabywca=nabywca,
            typ=typ,
            waluta=waluta,
            suma_netto=suma_netto,
            suma_vat=suma_vat,
            suma_brutto=suma_brutto,
            stawki_netto=stawki_netto,
            stawki_vat=stawki_vat,
            pozycje=pozycje,
            raw_xml=xml_content,
        )
