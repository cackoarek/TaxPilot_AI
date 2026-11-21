"""
Moduł deduplikacji faktur i wykrywania anomalii (InvoiceDeduplicator).
Chroni system przed:
1. Podwójnym ujęciem faktury pobranej z KSeF oraz równocześnie wgranej jako plik do non-ksef-raw (KSeF First).
2. Ponownym wgraniem tego samego dokumentu (np. paragonu lub faktury zagranicznej) w innym miesiącu (Cross-month deduplication).
3. Wielokrotnym wgraniem tego samego pliku w tym samym miesiącu.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Set, Any
import json

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType


class DuplicateType(str, Enum):
    KSEF_COLLISION = "KSEF_COLLISION"               # Faktura pobrana z KSeF i wgrana jako plik Non-KSeF
    CROSS_MONTH_DUPLICATE = "CROSS_MONTH_DUPLICATE" # Faktura wgrana powtórnie w innym miesiącu
    SAME_PERIOD_DUPLICATE = "SAME_PERIOD_DUPLICATE" # Zdublowany plik w tym samym miesiącu


@dataclass
class DuplicateAnomaly:
    """Informacja o wykrytym duplikacie faktury."""
    faktura_odrzucona: Invoice
    faktura_pierwotna: Invoice
    typ_duplikatu: DuplicateType
    miesiac_odrzucony: str
    rok_odrzucony: str
    miesiac_pierwotny: str
    rok_pierwotny: str
    plik_zrodlowy_odrzucony: str
    plik_zrodlowy_pierwotny: str
    opis_problemu: str
    rekomendacja: str

    def to_dict(self) -> Dict[str, Any]:
        kontrahent_nazwa = (
            self.faktura_odrzucona.sprzedawca.nazwa
            if self.faktura_odrzucona.typ == InvoiceType.KOSZT
            else self.faktura_odrzucona.nabywca.nazwa
        )
        kontrahent_nip = (
            self.faktura_odrzucona.sprzedawca.nip
            if self.faktura_odrzucona.typ == InvoiceType.KOSZT
            else self.faktura_odrzucona.nabywca.nip
        )
        return {
            "numer": self.faktura_odrzucona.numer,
            "kontrahent": kontrahent_nazwa,
            "kontrahent_nip": kontrahent_nip,
            "kwota_netto": str(self.faktura_odrzucona.suma_netto),
            "kwota_vat": str(self.faktura_odrzucona.suma_vat),
            "kwota_brutto": str(self.faktura_odrzucona.suma_brutto),
            "typ_duplikatu": self.typ_duplikatu.value,
            "miesiac_odrzucony": f"{self.rok_odrzucony}-{self.miesiac_odrzucony.zfill(2)}",
            "miesiac_pierwotny": f"{self.rok_pierwotny}-{self.miesiac_pierwotny.zfill(2)}",
            "zrodlo_odrzucone": getattr(self.faktura_odrzucona, "zrodlo", "NON_KSEF"),
            "zrodlo_pierwotne": getattr(self.faktura_pierwotna, "zrodlo", "KSEF"),
            "plik_odrzucony": self.plik_zrodlowy_odrzucony,
            "plik_pierwotny": self.plik_zrodlowy_pierwotny,
            "opis_problemu": self.opis_problemu,
            "rekomendacja": self.rekomendacja,
        }


def normalize_invoice_number(nr: Optional[str]) -> str:
    """Usuwa znaki interpunkcyjne, spacje i normalizuje do wielkich liter."""
    if not nr:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", nr).upper()


def extract_core_number(nr: Optional[str]) -> str:
    """Wyciąga trzon numeru po usunięciu powszechnych prefiksów typu FV, FAKTURA itp."""
    clean = normalize_invoice_number(nr)
    core = re.sub(r"^(?:FAKTURAVAT|FAKTURA|FVAT|FV|INVOICE|INV)", "", clean)
    return core if len(core) >= 3 else clean


def clean_nip(nip: Optional[str]) -> str:
    """Normalizuje NIP (usuwa myślniki, prefiks PL itp.)."""
    if not nip:
        return "0000000000"
    digits = re.sub(r"[^0-9A-Za-z]", "", nip).upper()
    if digits.startswith("PL") and len(digits) == 12:
        digits = digits[2:]
    return digits


class InvoiceDeduplicator:
    """
    Silnik wykrywania duplikatów i konfliktów źródłowych (KSeF vs Non-KSeF, Cross-Month).
    """

    @classmethod
    def are_invoices_matching(cls, inv1: Invoice, inv2: Invoice) -> Tuple[bool, str]:
        """
        Sprawdza, czy dwie faktury reprezentują to samo zdarzenie gospodarcze.
        Zwraca (czy_pasuja, uzasadnienie_dopasowania).
        """
        # 1. Zgodność typu (obie sprzedaż lub obie koszty)
        if inv1.typ != inv2.typ:
            return False, ""

        # 2. Identyfikacja kontrahenta
        if inv1.typ == InvoiceType.KOSZT:
            nip1 = clean_nip(inv1.sprzedawca.nip)
            nip2 = clean_nip(inv2.sprzedawca.nip)
            name1 = (inv1.sprzedawca.nazwa or "").strip().lower()
            name2 = (inv2.sprzedawca.nazwa or "").strip().lower()
        else:
            nip1 = clean_nip(inv1.nabywca.nip)
            nip2 = clean_nip(inv2.nabywca.nip)
            name1 = (inv1.nabywca.nazwa or "").strip().lower()
            name2 = (inv2.nabywca.nazwa or "").strip().lower()

        nip_match = (nip1 == nip2) and (nip1 != "0000000000")
        name_match = bool(name1 and name2 and (name1 in name2 or name2 in name1))
        contractor_match = nip_match or (name_match and (nip1 == "0000000000" or nip2 == "0000000000"))

        # 3. Zgodność numeru faktury
        num1_norm = normalize_invoice_number(inv1.numer)
        num2_norm = normalize_invoice_number(inv2.numer)
        num1_core = extract_core_number(inv1.numer)
        num2_core = extract_core_number(inv2.numer)

        num_exact_match = (bool(num1_norm) and num1_norm == num2_norm)
        num_core_match = (bool(num1_core) and bool(num2_core) and num1_core == num2_core)

        # Jeśli kontrahent i numer faktury pasują -> 100% dopasowanie
        if contractor_match and (num_exact_match or num_core_match):
            kontrahent_info = f"NIP: {nip1}" if nip1 != "0000000000" else f"Nazwa: {name1}"
            return True, f"Identyczny numer faktury ('{inv1.numer}' ~ '{inv2.numer}') oraz kontrahent ({kontrahent_info})"

        # 4. Dopasowanie po zawartości (kwota brutto + netto + data wystawienia + kontrahent)
        # Przydatne w przypadku paragonów / plików bez numeru lub z inną konwencją numeracji
        if (
            contractor_match
            and inv1.data_wystawienia
            and inv1.data_wystawienia == inv2.data_wystawienia
            and inv1.suma_brutto > Decimal("0.00")
            and abs(inv1.suma_brutto - inv2.suma_brutto) < Decimal("0.01")
            and abs(inv1.suma_netto - inv2.suma_netto) < Decimal("0.01")
        ):
            kontrahent_info = f"NIP: {nip1}" if nip1 != "0000000000" else f"Nazwa: {name1}"
            return True, (
                f"Identyczny kontrahent ({kontrahent_info}), data wystawienia ({inv1.data_wystawienia}) "
                f"oraz kwoty (brutto: {inv1.suma_brutto:.2f} zł, netto: {inv1.suma_netto:.2f} zł)"
            )

        return False, ""

    @classmethod
    def load_raw_month_invoices(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None
    ) -> Tuple[List[Tuple[Invoice, Path]], List[Tuple[Invoice, Path]]]:
        """
        Wczytuje z dysku wszystkie faktury z danego miesiąca z podziałem na:
        - ksef_invoices: lista krotek (Invoice, Path)
        - non_ksef_invoices: lista krotek (Invoice, Path)
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)
        base_path = profile.katalog_firmy / "faktury" / rok_str / miesiac_str

        ksef_list: List[Tuple[Invoice, Path]] = []
        non_ksef_list: List[Tuple[Invoice, Path]] = []

        if not base_path.exists():
            return ksef_list, non_ksef_list

        subfolders = [typ.value] if typ else ["sprzedaz", "koszty"]
        for sub in subfolders:
            sub_dir = base_path / sub
            if not sub_dir.exists():
                continue

            current_type = InvoiceType.SPRZEDAZ if sub == "sprzedaz" else InvoiceType.KOSZT

            # 1. KSeF
            ksef_dirs = []
            if (sub_dir / "ksef").exists():
                ksef_dirs.append(sub_dir / "ksef")
            ksef_dirs.append(sub_dir)  # dla wstecznej kompatybilności

            seen_paths = set()
            for k_dir in ksef_dirs:
                for json_file in sorted(k_dir.glob("*.json")):
                    if json_file.is_file() and json_file not in seen_paths:
                        seen_paths.add(json_file)
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            inv = Invoice.from_dict(data)
                            inv.typ = current_type
                            if not getattr(inv, "zrodlo", None):
                                inv.zrodlo = "KSEF"
                            if not getattr(inv, "plik_zrodlowy", None):
                                inv.plik_zrodlowy = str(json_file)

                            # Uzupełnij rachunek bankowy i dane z XML jeśli istnieją obok
                            xml_file = json_file.with_suffix(".xml")
                            if xml_file.exists() and (not inv.rachunek_bankowy or not inv.sprzedawca.regon):
                                try:
                                    with open(xml_file, "r", encoding="utf-8") as xf:
                                        xml_content = xf.read()
                                    from src.level_1_ingestion.ksef_parser import KSeFParser
                                    parsed_xml_inv = KSeFParser.parse_xml(xml_content, target_company_nip=profile.nip)
                                    if parsed_xml_inv.rachunek_bankowy and not inv.rachunek_bankowy:
                                        inv.rachunek_bankowy = parsed_xml_inv.rachunek_bankowy
                                    if parsed_xml_inv.sprzedawca.regon and not inv.sprzedawca.regon:
                                        inv.sprzedawca.regon = parsed_xml_inv.sprzedawca.regon
                                    if parsed_xml_inv.sprzedawca.adres and not inv.sprzedawca.adres:
                                        inv.sprzedawca.adres = parsed_xml_inv.sprzedawca.adres
                                    # Zaktualizuj json
                                    with open(json_file, "w", encoding="utf-8") as jf:
                                        json.dump(inv.to_dict(), jf, indent=2, ensure_ascii=False)
                                except Exception:
                                    pass

                            ksef_list.append((inv, json_file))
                        except Exception:
                            continue

            # 2. Non-KSeF
            ext_dir = sub_dir / "non-ksef-extracted"
            if ext_dir.exists():
                for json_file in sorted(ext_dir.glob("*.json")):
                    if json_file.is_file() and json_file not in seen_paths:
                        seen_paths.add(json_file)
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            inv = Invoice.from_dict(data)
                            inv.typ = current_type
                            inv.zrodlo = "NON_KSEF"
                            if not getattr(inv, "plik_zrodlowy", None):
                                inv.plik_zrodlowy = str(json_file)
                            non_ksef_list.append((inv, json_file))
                        except Exception:
                            continue

        return ksef_list, non_ksef_list

    @classmethod
    def scan_archive_for_historical_invoices(
        cls, profile: CompanyProfile, exclude_rok: str, exclude_miesiac: str, typ: Optional[InvoiceType] = None
    ) -> List[Tuple[str, str, Invoice, Path]]:
        """
        Skanuje całe archiwum firmy za wszystkie INNE miesiące niż (exclude_rok, exclude_miesiac).
        Zwraca listę (rok, miesiac, invoice, json_path).
        """
        historical: List[Tuple[str, str, Invoice, Path]] = []
        faktury_dir = profile.katalog_firmy / "faktury"
        if not faktury_dir.exists():
            return historical

        exclude_m_str = str(exclude_miesiac).zfill(2)
        exclude_r_str = str(exclude_rok)

        for r_path in sorted(faktury_dir.iterdir()):
            if not r_path.is_dir() or not r_path.name.isdigit():
                continue
            r_str = r_path.name
            for m_path in sorted(r_path.iterdir()):
                if not m_path.is_dir():
                    continue
                m_str = m_path.name.zfill(2)
                if r_str == exclude_r_str and m_str == exclude_m_str:
                    continue

                ksef_invs, non_ksef_invs = cls.load_raw_month_invoices(profile, r_str, m_str, typ=typ)
                for inv, path in ksef_invs:
                    historical.append((r_str, m_str, inv, path))
                for inv, path in non_ksef_invs:
                    historical.append((r_str, m_str, inv, path))

        return historical

    @classmethod
    def deduplicate_month(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None
    ) -> Tuple[List[Invoice], List[DuplicateAnomaly]]:
        """
        Przeprowadza pełną deduplikację faktur za wskazany miesiąc.
        
        Zwraca:
        - clean_invoices: lista poprawnych, unikalnych faktur do zaksięgowania.
        - anomalies: lista wykrytych duplikatów z pełnym uzasadnieniem (do przedstawienia użytkownikowi).
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        # 1. Wczytaj faktury z bieżącego miesiąca
        ksef_list, non_ksef_list = cls.load_raw_month_invoices(profile, rok_str, miesiac_str, typ=typ)

        # 2. Wczytaj historię z pozostałych miesięcy
        historical_invoices = cls.scan_archive_for_historical_invoices(
            profile, exclude_rok=rok_str, exclude_miesiac=miesiac_str, typ=typ
        )

        clean_invoices: List[Invoice] = []
        anomalies: List[DuplicateAnomaly] = []

        # Zbiory przyjętych faktur KSeF w bieżącym miesiącu
        accepted_ksef: List[Invoice] = []
        for inv, path in ksef_list:
            # Weryfikacja czy w KSeF w bieżącym miesiącu nie ma przypadkiem podwójnego pliku
            already_in = False
            for prev in accepted_ksef:
                match, reason = cls.are_invoices_matching(inv, prev)
                if match:
                    already_in = True
                    break
            if not already_in:
                accepted_ksef.append(inv)
                clean_invoices.append(inv)

        accepted_non_ksef: List[Invoice] = []

        # 3. Weryfikacja faktur Non-KSeF pod kątem kolizji
        for non_ksef_inv, non_ksef_path in non_ksef_list:
            rejected = False
            odrzucony_plik = non_ksef_inv.plik_zrodlowy or non_ksef_path.name
            kontrahent = (
                non_ksef_inv.sprzedawca.nazwa
                if non_ksef_inv.typ == InvoiceType.KOSZT
                else non_ksef_inv.nabywca.nazwa
            )

            # --- Reguła 1: Kolizja z KSeF w bieżącym miesiącu ---
            for ksef_inv in accepted_ksef:
                match, reason = cls.are_invoices_matching(non_ksef_inv, ksef_inv)
                if match:
                    anomalies.append(
                        DuplicateAnomaly(
                            faktura_odrzucona=non_ksef_inv,
                            faktura_pierwotna=ksef_inv,
                            typ_duplikatu=DuplicateType.KSEF_COLLISION,
                            miesiac_odrzucony=miesiac_str,
                            rok_odrzucony=rok_str,
                            miesiac_pierwotny=miesiac_str,
                            rok_pierwotny=rok_str,
                            plik_zrodlowy_odrzucony=odrzucony_plik,
                            plik_zrodlowy_pierwotny=ksef_inv.plik_zrodlowy or ksef_inv.bezpieczny_numer_pliku,
                            opis_problemu=(
                                f"Faktura '{non_ksef_inv.numer}' od {kontrahent} "
                                f"({non_ksef_inv.suma_brutto:.2f} zł brutto) została oficjalnie pobrana z KSeF, "
                                f"a jednocześnie wgrana jako plik '{odrzucony_plik}' do folderu non-ksef-raw."
                            ),
                            rekomendacja=(
                                "Zdublowany plik z non-ksef został wykluczony z księgowania. "
                                "Faktura jest ujęta wyłącznie raz na podstawie wiarygodnych danych z KSeF."
                            ),
                        )
                    )
                    rejected = True
                    break

            if rejected:
                continue

            # --- Reguła 2: Kolizja z KSeF w INNYM miesiącu ---
            for hist_r, hist_m, hist_inv, hist_path in historical_invoices:
                if getattr(hist_inv, "zrodlo", "") == "KSEF":
                    match, reason = cls.are_invoices_matching(non_ksef_inv, hist_inv)
                    if match:
                        anomalies.append(
                            DuplicateAnomaly(
                                faktura_odrzucona=non_ksef_inv,
                                faktura_pierwotna=hist_inv,
                                typ_duplikatu=DuplicateType.KSEF_COLLISION,
                                miesiac_odrzucony=miesiac_str,
                                rok_odrzucony=rok_str,
                                miesiac_pierwotny=hist_m,
                                rok_pierwotny=hist_r,
                                plik_zrodlowy_odrzucony=odrzucony_plik,
                                plik_zrodlowy_pierwotny=hist_inv.plik_zrodlowy or hist_path.name,
                                opis_problemu=(
                                    f"Faktura '{non_ksef_inv.numer}' od {kontrahent} "
                                    f"({non_ksef_inv.suma_brutto:.2f} zł brutto) istnieje już w KSeF "
                                    f"w miesiącu {hist_r}-{hist_m}. Wykryto próbę ponownego ujęcia z pliku "
                                    f"'{odrzucony_plik}' w miesiącu {rok_str}-{miesiac_str}."
                                ),
                                rekomendacja=(
                                    "Plik został wykluczony z bieżącego rozliczenia, aby zapobiec "
                                    "podwójnemu odliczeniu VAT i podwójnemu zaliczeniu do kosztów."
                                ),
                            )
                        )
                        rejected = True
                        break

            if rejected:
                continue

            # --- Reguła 3: Kolizja z Non-KSeF w INNYM miesiącu (Cross-Month Duplicate) ---
            for hist_r, hist_m, hist_inv, hist_path in historical_invoices:
                if getattr(hist_inv, "zrodlo", "") != "KSEF":
                    match, reason = cls.are_invoices_matching(non_ksef_inv, hist_inv)
                    if match:
                        anomalies.append(
                            DuplicateAnomaly(
                                faktura_odrzucona=non_ksef_inv,
                                faktura_pierwotna=hist_inv,
                                typ_duplikatu=DuplicateType.CROSS_MONTH_DUPLICATE,
                                miesiac_odrzucony=miesiac_str,
                                rok_odrzucony=rok_str,
                                miesiac_pierwotny=hist_m,
                                rok_pierwotny=hist_r,
                                plik_zrodlowy_odrzucony=odrzucony_plik,
                                plik_zrodlowy_pierwotny=hist_inv.plik_zrodlowy or hist_path.name,
                                opis_problemu=(
                                    f"Faktura/paragon '{non_ksef_inv.numer}' od {kontrahent} "
                                    f"({non_ksef_inv.suma_brutto:.2f} zł brutto) została już uprzednio zaksięgowana "
                                    f"w miesiącu {hist_r}-{hist_m} (plik: '{hist_inv.plik_zrodlowy or hist_path.name}'). "
                                    f"Wykryto ponowne wgranie tego samego dokumentu (plik: '{odrzucony_plik}') "
                                    f"w miesiącu {rok_str}-{miesiac_str}."
                                ),
                                rekomendacja=(
                                    "Zdublowany dokument został pominięty w bieżącym miesiącu. "
                                    "Zapobieżono podwójnemu księgowaniu."
                                ),
                            )
                        )
                        rejected = True
                        break

            if rejected:
                continue

            # --- Reguła 4: Kolizja z innym Non-KSeF w TYM SAMYM miesiącu ---
            for prev_non_ksef in accepted_non_ksef:
                match, reason = cls.are_invoices_matching(non_ksef_inv, prev_non_ksef)
                if match:
                    anomalies.append(
                        DuplicateAnomaly(
                            faktura_odrzucona=non_ksef_inv,
                            faktura_pierwotna=prev_non_ksef,
                            typ_duplikatu=DuplicateType.SAME_PERIOD_DUPLICATE,
                            miesiac_odrzucony=miesiac_str,
                            rok_odrzucony=rok_str,
                            miesiac_pierwotny=miesiac_str,
                            rok_pierwotny=rok_str,
                            plik_zrodlowy_odrzucony=odrzucony_plik,
                            plik_zrodlowy_pierwotny=prev_non_ksef.plik_zrodlowy or prev_non_ksef.bezpieczny_numer_pliku,
                            opis_problemu=(
                                f"Faktura '{non_ksef_inv.numer}' od {kontrahent} "
                                f"({non_ksef_inv.suma_brutto:.2f} zł brutto) została wgrana wielokrotnie "
                                f"w tym samym miesiącu (plik '{odrzucony_plik}' duplikuje plik '{prev_non_ksef.plik_zrodlowy}')."
                            ),
                            rekomendacja=(
                                "Zdublowany plik został pominięty. Dokument zostanie ujęty w księgowaniu tylko raz."
                            ),
                        )
                    )
                    rejected = True
                    break

            if not rejected:
                accepted_non_ksef.append(non_ksef_inv)
                clean_invoices.append(non_ksef_inv)

        return clean_invoices, anomalies
