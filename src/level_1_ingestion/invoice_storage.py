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
import json
from typing import Tuple, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType
from src.level_1_ingestion.invoice_deduplicator import InvoiceDeduplicator, DuplicateAnomaly


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
        base_dir = cls.get_sprzedaz_dir(profile, rok, miesiac) if typ == InvoiceType.SPRZEDAZ else cls.get_koszty_dir(profile, rok, miesiac)
        d = base_dir / "non-ksef-raw"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def get_non_ksef_extracted_dir(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: InvoiceType = InvoiceType.KOSZT
    ) -> Path:
        base_dir = cls.get_sprzedaz_dir(profile, rok, miesiac) if typ == InvoiceType.SPRZEDAZ else cls.get_koszty_dir(profile, rok, miesiac)
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
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(invoice.to_dict(), f, indent=2, ensure_ascii=False)

        xml_path = target_dir / f"{base_filename}.xml"
        if invoice.raw_xml:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(invoice.raw_xml)

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
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(invoice.to_dict(), f, indent=2, ensure_ascii=False)

        return json_path

    @classmethod
    def list_invoices(cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None) -> List[Invoice]:
        """
        Zwraca listę unikalnych, zweryfikowanych faktur do zaksięgowania z danego miesiąca i roku.
        Przeprowadza pełną deduplikację przy użyciu InvoiceDeduplicator:
        - priorytet dla faktur KSeF (KSeF First)
        - eliminacja zdublowanych plików w non-ksef-raw
        - eliminacja duplikatów z innych miesięcy (Cross-Month Deduplication).
        """
        clean_invoices, _ = InvoiceDeduplicator.deduplicate_month(
            profile=profile, rok=rok, miesiac=miesiac, typ=typ
        )
        return clean_invoices

    @classmethod
    def get_duplicate_anomalies(
        cls, profile: CompanyProfile, rok: str, miesiac: str, typ: Optional[InvoiceType] = None
    ) -> List[DuplicateAnomaly]:
        """
        Zwraca listę wykrytych anomalii duplikatów dla danego miesiąca.
        """
        _, anomalies = InvoiceDeduplicator.deduplicate_month(
            profile=profile, rok=rok, miesiac=miesiac, typ=typ
        )
        return anomalies
