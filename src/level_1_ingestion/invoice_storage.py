"""
Moduł zapisu i organizacji faktur w strukturze katalogów firmy.
Struktura:
firmy/{NIP-Nazwa}/faktury/{rok}/{miesiac}/
├── sprzedaz/
│   ├── ksef/
│   ├── non-ksef-raw/
│   └── non-ksef-extracted/
└── koszty/
    ├── ksef/
    ├── non-ksef-raw/
    └── non-ksef-extracted/
"""

from pathlib import Path
from typing import List, Optional, Tuple

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType
from src.core.io import atomic_write_json, atomic_write_text
from src.level_1_ingestion.invoice_deduplicator import DuplicateAnomaly, InvoiceDeduplicator


class InvoiceStorage:
    """
    Zarządza fizycznym zapisem faktur w odpowiednich katalogach firmy.
    Obsługuje pełną symetrię pomiędzy sprzedażą a kosztami:
    - sprzedaż z KSeF: sprzedaz/ksef/
    - sprzedaż spoza KSeF: surowe w sprzedaz/non-ksef-raw/, wyekstrahowane w sprzedaz/non-ksef-extracted/
    - koszty z KSeF: koszty/ksef/
    - koszty spoza KSeF: surowe w koszty/non-ksef-raw/, wyekstrahowane w koszty/non-ksef-extracted/
    """

    @classmethod
    def get_sprzedaz_dir(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        return profile.katalog_firmy / "faktury" / str(rok) / str(miesiac).zfill(2) / "sprzedaz"

    @classmethod
    def get_ksef_sprzedaz_dir(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        d = cls.get_sprzedaz_dir(profile, rok, miesiac) / "ksef"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_koszty_dir(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        return profile.katalog_firmy / "faktury" / str(rok) / str(miesiac).zfill(2) / "koszty"

    @classmethod
    def get_ksef_koszty_dir(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        d = cls.get_koszty_dir(profile, rok, miesiac) / "ksef"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_non_ksef_raw_dir(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: InvoiceType = InvoiceType.KOSZT
    ) -> Path:
        base_dir = (
            cls.get_sprzedaz_dir(profile, rok, miesiac)
            if typ == InvoiceType.SPRZEDAZ
            else cls.get_koszty_dir(profile, rok, miesiac)
        )
        d = base_dir / "non-ksef-raw"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_non_ksef_extracted_dir(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: InvoiceType = InvoiceType.KOSZT
    ) -> Path:
        base_dir = (
            cls.get_sprzedaz_dir(profile, rok, miesiac)
            if typ == InvoiceType.SPRZEDAZ
            else cls.get_koszty_dir(profile, rok, miesiac)
        )
        d = base_dir / "non-ksef-extracted"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def ensure_month_directories(cls, profile: CompanyProfile, rok: str, miesiac: str):
        """Upewnia się, że pełna struktura katalogów dla miesiąca istnieje."""
        base = profile.katalog_firmy / "faktury" / str(rok) / str(miesiac).zfill(2)
        for sub in ["sprzedaz", "koszty"]:
            (base / sub / "ksef").mkdir(parents=True, exist_ok=True)
            (base / sub / "non-ksef-raw").mkdir(parents=True, exist_ok=True)
            (base / sub / "non-ksef-extracted").mkdir(parents=True, exist_ok=True)

    @classmethod
    def save_invoice(cls, profile: CompanyProfile, invoice: Invoice) -> Tuple[Path, Path]:
        """
        Zapisuje fakturę KSeF (plik JSON z metadanymi oraz plik XML jeśli dostępny)
        w odpowiednim katalogu:
        - sprzedaż: faktury/{rok}/{miesiac}/sprzedaz/ksef/
        - koszty: faktury/{rok}/{miesiac}/koszty/ksef/
        """
        rok = invoice.rok
        miesiac = invoice.miesiac.zfill(2)

        if invoice.typ == InvoiceType.SPRZEDAZ:
            target_dir = cls.get_ksef_sprzedaz_dir(profile, rok, miesiac)
        else:
            target_dir = cls.get_ksef_koszty_dir(profile, rok, miesiac)

        base_filename = invoice.bezpieczny_numer_pliku
        json_path = target_dir / f"{base_filename}.json"
        atomic_write_json(json_path, invoice.to_dict(), indent=2, ensure_ascii=False)

        xml_path = target_dir / f"{base_filename}.xml"
        if invoice.raw_xml:
            atomic_write_text(xml_path, invoice.raw_xml)

        return json_path, xml_path

    @classmethod
    def save_non_ksef_invoice(
        cls,
        profile: CompanyProfile,
        invoice: Invoice,
        typ: InvoiceType = InvoiceType.KOSZT,
        raw_source_name: Optional[str] = None,
        target_rok: Optional[str] = None,
        target_miesiac: Optional[str] = None,
    ) -> Path:
        """
        Zapisuje wyekstrahowaną encję faktury non-ksef do katalogu:
        faktury/{rok}/{miesiac}/{typ}/non-ksef-extracted/{nazwa}.json
        """
        invoice.typ = typ
        invoice.zrodlo = "NON_KSEF"
        if raw_source_name:
            invoice.plik_zrodlowy = raw_source_name

        rok = str(target_rok) if target_rok else invoice.rok
        miesiac = str(target_miesiac).zfill(2) if target_miesiac else invoice.miesiac.zfill(2)
        target_dir = cls.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=typ)

        if raw_source_name:
            stem = Path(raw_source_name).stem
            filename = f"{stem}.json"
        else:
            filename = f"{invoice.bezpieczny_numer_pliku}.json"

        json_path = target_dir / filename
        atomic_write_json(json_path, invoice.to_dict(), indent=2, ensure_ascii=False)

        return json_path

    @classmethod
    def list_invoices(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None
    ) -> List[Invoice]:
        """
        Zwraca listę unikalnych, zweryfikowanych faktur do zaksięgowania z danego miesiąca i roku.
        Przeprowadza pełną deduplikację przy użyciu InvoiceDeduplicator:
        - priorytet dla faktur KSeF (KSeF First)
        - eliminacja zdublowanych plików w non-ksef-raw
        - eliminacja duplikatów z innych miesięcy (Cross-Month Deduplication).
        """
        clean_invoices, _ = InvoiceDeduplicator.deduplicate_month(profile=profile, rok=rok, miesiac=miesiac, typ=typ)
        return clean_invoices

    @classmethod
    def list_sales_invoices_for_pit(cls, profile: CompanyProfile, rok: str, miesiac: str) -> List[Invoice]:
        """
        Zwraca faktury sprzedaży podlegające ujęciu w Ewidencji Przychodów (PIT-28) za dany miesiąc.
        Zgodnie z art. 14 ust. 1m ustawy o PIT w zw. z art. 12 ust. 11 ustawy o zryczałtowanym podatku:
        - Korekta przychodu spowodowana błędem rachunkowym koryguje przychód wstecznie w okresie
          pierwotnym (miesiąc faktury korygowanej / daty sprzedaży), a nie w miesiącu jej wystawienia.
        - Dlatego z bieżącego miesiąca wykluczamy korekty wsteczne dotyczące innych miesięcy,
          a dołączamy korekty wsteczne wystawione w późniejszych miesiącach roku, których okres korygowany to ten miesiąc.
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)
        m_int = int(miesiac_str)

        # 1. Faktury sprzedaży z bieżącego miesiąca
        current_invoices = cls.list_invoices(profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.SPRZEDAZ)
        result: List[Invoice] = []
        seen_numbers = set()

        for inv in current_invoices:
            if inv.czy_korekta and inv.czy_korekta_wsteczna_pit:
                # Jeśli korekta wsteczna dotyczy INNEGO miesiąca niż bieżący, pomijamy ją w PIT za ten miesiąc
                if inv.okres_rozliczeniowy_pit != (rok_str, miesiac_str):
                    continue
            result.append(inv)
            seen_numbers.add(inv.numer)

        # 2. Poszukiwanie korekt wstecznych wystawionych w późniejszych miesiącach tego samego roku
        year_dir = profile.katalog_firmy / "faktury" / rok_str
        if year_dir.exists():
            for m in range(m_int + 1, 13):
                m_future_str = f"{m:02d}"
                future_invoices = cls.list_invoices(
                    profile, rok=rok_str, miesiac=m_future_str, typ=InvoiceType.SPRZEDAZ
                )
                for inv in future_invoices:
                    if inv.czy_korekta and inv.czy_korekta_wsteczna_pit:
                        if inv.okres_rozliczeniowy_pit == (rok_str, miesiac_str):
                            if inv.numer not in seen_numbers:
                                result.append(inv)
                                seen_numbers.add(inv.numer)

        return result

    @classmethod
    def get_duplicate_anomalies(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None
    ) -> List[DuplicateAnomaly]:
        """
        Zwraca listę wykrytych anomalii duplikatów dla danego miesiąca.
        """
        _, anomalies = InvoiceDeduplicator.deduplicate_month(profile=profile, rok=rok, miesiac=miesiac, typ=typ)
        return anomalies
