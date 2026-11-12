"""
Modele danych faktur, pozycji i stron transakcji.
Używa Decimal do precyzyjnych obliczeń finansowych.
"""

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
from typing import List, Dict, Optional, Any
import json
import re


class InvoiceType(str, Enum):
    SPRZEDAZ = "sprzedaz"  # Faktura wystawiona przez podatnika (przychód)
    KOSZT = "koszty"       # Faktura wystawiona na podatnika (koszt/wydatek)


@dataclass
class InvoiceParty:
    nip: str
    nazwa: str
    kraj: str = "PL"
    adres: Optional[str] = None
    regon: Optional[str] = None

    def __post_init__(self):
        self.nip = re.sub(r"[^0-9A-Za-z]", "", self.nip)


@dataclass
class InvoiceItem:
    opis: str
    ilosc: Decimal = Decimal("1")
    jednostka: str = "szt"
    cena_jednostkowa_netto: Decimal = Decimal("0.00")
    wartosc_netto: Decimal = Decimal("0.00")
    stawka_vat: str = "23"  # "23", "8", "5", "0", "zw", "oo"
    kwota_vat: Decimal = Decimal("0.00")
    wartosc_brutto: Decimal = Decimal("0.00")
    stawka_ryczaltu: Optional[Decimal] = None  # np. Decimal("0.12") dla ryczałtu 12%
    pkwiu: Optional[str] = None


@dataclass
class Invoice:
    numer: str
    data_wystawienia: str  # YYYY-MM-DD
    sprzedawca: InvoiceParty
    nabywca: InvoiceParty
    typ: InvoiceType
    suma_netto: Decimal
    suma_vat: Decimal
    suma_brutto: Decimal
    data_sprzedazy: Optional[str] = None
    waluta: str = "PLN"
    ksef_numer_referencyjny: Optional[str] = None
    pozycje: List[InvoiceItem] = field(default_factory=list)
    stawki_netto: Dict[str, Decimal] = field(default_factory=dict)
    stawki_vat: Dict[str, Decimal] = field(default_factory=dict)
    raw_xml: Optional[str] = None
    zrodlo: str = "KSEF"  # "KSEF" lub "NON_KSEF"
    plik_zrodlowy: Optional[str] = None
    rodzaj_faktury: Optional[str] = "VAT"
    przyczyna_korekty: Optional[str] = None
    nr_faktury_korygowanej: Optional[str] = None
    data_faktury_korygowanej: Optional[str] = None
    rachunek_bankowy: Optional[str] = None

    @property
    def czy_korekta(self) -> bool:
        return (
            (self.rodzaj_faktury and self.rodzaj_faktury.upper() == "KOR")
            or "KOR" in self.numer.upper()
            or self.suma_brutto < Decimal("0.00")
            or self.suma_netto < Decimal("0.00")
        )

    @property
    def czy_korekta_wsteczna_pit(self) -> bool:
        """
        Zgodnie z art. 14 ust. 1m ustawy o PIT:
        Korekta przychodu spowodowana błędem rachunkowym lub inną oczywistą omyłką
        jest rozliczana wstecznie w okresie, w którym wykazano pierwotny przychód,
        a nie w bieżącym okresie rozliczeniowym.
        """
        if not self.czy_korekta:
            return False
        przyczyna = (self.przyczyna_korekty or "").lower()
        if "błąd rachunkowy" in przyczyna or "omyłk" in przyczyna:
            return True
        return False

    @property
    def okres_rozliczeniowy(self) -> tuple[str, str]:
        """
        Wyznacza właściwy okres podatkowo-księgowy (rok, miesiac):
        - Dla sprzedaży korygującej (in-minus KSeF): data wystawienia faktury korygującej (art. 29a ust. 13 VAT).
        - Dla sprzedaży standardowej: data sprzedaży (wykonania usługi) lub data wystawienia (art. 19a VAT / art. 14 PIT).
        - Dla kosztów (zakupów): data otrzymania/wystawienia faktury, nie wcześniej niż data sprzedaży
          (zgodnie z art. 86 ust. 10b pkt 1 ustawy o VAT: prawo do odliczenia podatku naliczonego
          powstaje nie wcześniej niż w okresie, w którym podatnik otrzymał fakturę).
        """
        if self.typ == InvoiceType.SPRZEDAZ:
            if self.czy_korekta:
                dt = self.data_wystawienia
            else:
                dt = self.data_sprzedazy or self.data_wystawienia
        else:
            if self.data_sprzedazy and self.data_wystawienia:
                dt = max(self.data_sprzedazy, self.data_wystawienia)
            else:
                dt = self.data_wystawienia or self.data_sprzedazy
        parts = dt.split("-")
        return parts[0], parts[1].zfill(2)

    @property
    def rok(self) -> str:
        return self.okres_rozliczeniowy[0]

    @property
    def miesiac(self) -> str:
        return self.okres_rozliczeniowy[1]

    @property
    def bezpieczny_numer_pliku(self) -> str:
        safe_num = re.sub(r"[^\w\-_]", "_", self.numer)
        return f"{self.data_wystawienia}_{safe_num}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer": self.numer,
            "ksef_numer_referencyjny": self.ksef_numer_referencyjny,
            "zrodlo": self.zrodlo,
            "plik_zrodlowy": self.plik_zrodlowy,
            "data_wystawienia": self.data_wystawienia,
            "data_sprzedazy": self.data_sprzedazy,
            "typ": self.typ.value,
            "waluta": self.waluta,
            "rodzaj_faktury": self.rodzaj_faktury,
            "przyczyna_korekty": self.przyczyna_korekty,
            "nr_faktury_korygowanej": self.nr_faktury_korygowanej,
            "data_faktury_korygowanej": self.data_faktury_korygowanej,
            "rachunek_bankowy": self.rachunek_bankowy,
            "sprzedawca": asdict(self.sprzedawca),
            "nabywca": asdict(self.nabywca),
            "suma_netto": str(self.suma_netto),
            "suma_vat": str(self.suma_vat),
            "suma_brutto": str(self.suma_brutto),
            "stawki_netto": {k: str(v) for k, v in self.stawki_netto.items()},
            "stawki_vat": {k: str(v) for k, v in self.stawki_vat.items()},
            "pozycje": [
                {
                    "opis": p.opis,
                    "ilosc": str(p.ilosc),
                    "jednostka": p.jednostka,
                    "cena_jednostkowa_netto": str(p.cena_jednostkowa_netto),
                    "wartosc_netto": str(p.wartosc_netto),
                    "stawka_vat": p.stawka_vat,
                    "kwota_vat": str(p.kwota_vat),
                    "wartosc_brutto": str(p.wartosc_brutto),
                    "stawka_ryczaltu": str(p.stawka_ryczaltu) if p.stawka_ryczaltu is not None else None,
                    "pkwiu": p.pkwiu,
                }
                for p in self.pozycje
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Invoice":
        sprzedawca = InvoiceParty(
            nip=data["sprzedawca"]["nip"],
            nazwa=data["sprzedawca"]["nazwa"],
            kraj=data["sprzedawca"].get("kraj", "PL"),
            adres=data["sprzedawca"].get("adres"),
            regon=data["sprzedawca"].get("regon"),
        )
        nabywca = InvoiceParty(
            nip=data["nabywca"]["nip"],
            nazwa=data["nabywca"]["nazwa"],
            kraj=data["nabywca"].get("kraj", "PL"),
            adres=data["nabywca"].get("adres"),
            regon=data["nabywca"].get("regon"),
        )
        pozycje = [
            InvoiceItem(
                opis=p["opis"],
                ilosc=Decimal(str(p.get("ilosc", "1"))),
                jednostka=p.get("jednostka", "szt"),
                cena_jednostkowa_netto=Decimal(str(p.get("cena_jednostkowa_netto", "0.00"))),
                wartosc_netto=Decimal(str(p.get("wartosc_netto", "0.00"))),
                stawka_vat=str(p.get("stawka_vat", "23")),
                kwota_vat=Decimal(str(p.get("kwota_vat", "0.00"))),
                wartosc_brutto=Decimal(str(p.get("wartosc_brutto", "0.00"))),
                stawka_ryczaltu=Decimal(str(p["stawka_ryczaltu"])) if p.get("stawka_ryczaltu") is not None else None,
                pkwiu=p.get("pkwiu"),
            )
            for p in data.get("pozycje", [])
        ]
        raw_typ = str(data.get("typ", "koszty")).lower()
        if raw_typ in ["sprzedaz", "sprzedaż", "sales"]:
            inv_type = InvoiceType.SPRZEDAZ
        else:
            inv_type = InvoiceType.KOSZT

        return cls(
            numer=data["numer"],
            data_wystawienia=data["data_wystawienia"],
            sprzedawca=sprzedawca,
            nabywca=nabywca,
            typ=inv_type,
            suma_netto=Decimal(str(data["suma_netto"])),
            suma_vat=Decimal(str(data["suma_vat"])),
            suma_brutto=Decimal(str(data["suma_brutto"])),
            data_sprzedazy=data.get("data_sprzedazy"),
            waluta=data.get("waluta", "PLN"),
            ksef_numer_referencyjny=data.get("ksef_numer_referencyjny"),
            pozycje=pozycje,
            stawki_netto={k: Decimal(str(v)) for k, v in data.get("stawki_netto", {}).items()},
            stawki_vat={k: Decimal(str(v)) for k, v in data.get("stawki_vat", {}).items()},
            raw_xml=data.get("raw_xml"),
            zrodlo=data.get("zrodlo", "KSEF"),
            plik_zrodlowy=data.get("plik_zrodlowy"),
            rodzaj_faktury=data.get("rodzaj_faktury", "VAT"),
            przyczyna_korekty=data.get("przyczyna_korekty"),
            nr_faktury_korygowanej=data.get("nr_faktury_korygowanej"),
            data_faktury_korygowanej=data.get("data_faktury_korygowanej"),
            rachunek_bankowy=data.get("rachunek_bankowy"),
        )
