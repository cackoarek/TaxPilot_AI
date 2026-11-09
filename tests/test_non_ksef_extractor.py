"""
Testy jednostkowe modułu ekstrakcji i obsługi faktur kosztowych Non-KSeF (NonKSeFExtractor).
"""

import json
import shutil
import unittest
from decimal import Decimal
from pathlib import Path

from src.core.company import CompanyProfile, KSeFConfig
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.level_2_bookkeeping.ledger import BookkeepingService
from src.skills.pre_settlement_review import PreSettlementReview


class TestNonKSeFExtractor(unittest.TestCase):

    def setUp(self):
        self.profile = CompanyProfile(
            nip="7770001122",
            nazwa="CloudTech Solutions Jan Kowalski",
            katalog_nazwa="7770001122-CloudTech_Solutions_Jan_Kowalski",
            ksef=KSeFConfig(srodowisko="TEST"),
        )
        self.test_rok = "2026"
        self.test_miesiac = "11"

        self.raw_dir = InvoiceStorage.get_non_ksef_raw_dir(self.profile, self.test_rok, self.test_miesiac, typ=InvoiceType.KOSZT)
        self.extracted_dir = InvoiceStorage.get_non_ksef_extracted_dir(self.profile, self.test_rok, self.test_miesiac, typ=InvoiceType.KOSZT)

        self.sales_raw_dir = InvoiceStorage.get_non_ksef_raw_dir(self.profile, self.test_rok, self.test_miesiac, typ=InvoiceType.SPRZEDAZ)
        self.sales_extracted_dir = InvoiceStorage.get_non_ksef_extracted_dir(self.profile, self.test_rok, self.test_miesiac, typ=InvoiceType.SPRZEDAZ)

    def tearDown(self):
        test_dir = self.profile.katalog_firmy
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_extract_from_json(self):
        # 1. Tworzymy surowy plik w non-ksef-raw
        raw_json_data = {
            "invoice_number": "INV-GCLOUD-2026-11",
            "issue_date": "2026-11-03",
            "seller": {
                "name": "Google Cloud Poland Sp. z o.o.",
                "nip": "5252834567",
                "country": "PL"
            },
            "net_amount": "500.00",
            "vat_amount": "115.00",
            "gross_amount": "615.00",
            "items": [
                {
                    "description": "Google Cloud Platform - Compute Engine & Cloud Run",
                    "net": "500.00",
                    "vat": "115.00",
                    "gross": "615.00",
                    "vat_rate": "23"
                }
            ]
        }
        raw_path = self.raw_dir / "test_google_cloud.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_json_data, f)

        # 2. Wywołujemy ekstrakcję
        extracted_files = NonKSeFExtractor.extract_all(self.profile, self.test_rok, self.test_miesiac, force=True)
        self.assertTrue(any(f.name == "test_google_cloud.json" for f in extracted_files))

        # 3. Sprawdzamy wyekstrahowany plik JSON
        target_path = self.extracted_dir / "test_google_cloud.json"
        self.assertTrue(target_path.exists())

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["numer"], "INV-GCLOUD-2026-11")
        self.assertEqual(data["zrodlo"], "NON_KSEF")
        self.assertEqual(data["plik_zrodlowy"], "test_google_cloud.json")
        self.assertEqual(Decimal(data["suma_netto"]), Decimal("500.00"))
        self.assertEqual(Decimal(data["suma_vat"]), Decimal("115.00"))
        self.assertEqual(Decimal(data["suma_brutto"]), Decimal("615.00"))
        self.assertEqual(data["sprzedawca"]["nip"], "5252834567")

    def test_extract_from_text(self):
        # 1. Tworzymy surowy plik tekstowy w non-ksef-raw
        raw_text = """
        FAKTURA VAT NR: HOST/2026/11/99
        Data wystawienia: 2026-11-04
        Data sprzedaży: 2026-11-04

        Sprzedawca: OVH Sp. z o.o.
        NIP: 8992520556

        Nabywca: CloudTech Solutions Jan Kowalski
        NIP: 7770001122

        Pozycje:
        Serwer Dedykowany NVMe - 200,00 zł Netto
        Stawka VAT: 23%
        Podatek VAT: 46,00 zł
        Razem Brutto: 246,00 zł
        """
        raw_path = self.raw_dir / "test_hosting_faktura.txt"
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_text)

        # 2. Wywołujemy ekstrakcję
        extracted_files = NonKSeFExtractor.extract_all(self.profile, self.test_rok, self.test_miesiac, force=True)
        self.assertTrue(any(f.name == "test_hosting_faktura.json" for f in extracted_files))

        # 3. Sprawdzamy wyekstrahowany plik
        target_path = self.extracted_dir / "test_hosting_faktura.json"
        self.assertTrue(target_path.exists())

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["numer"], "HOST/2026/11/99")
        self.assertEqual(data["zrodlo"], "NON_KSEF")
        self.assertEqual(data["sprzedawca"]["nip"], "8992520556")
        self.assertEqual(Decimal(data["suma_netto"]), Decimal("200.00"))
        self.assertEqual(Decimal(data["suma_vat"]), Decimal("46.00"))
        self.assertEqual(Decimal(data["suma_brutto"]), Decimal("246.00"))

    def test_list_invoices_and_pre_settlement_review_with_non_ksef(self):
        # Utwórz plik w non-ksef-raw
        raw_json_data = {
            "numer": "TEST-NONKSEF-01",
            "data_wystawienia": "2026-11-05",
            "data_sprzedazy": "2026-11-05",
            "typ": "koszty",
            "suma_netto": "100.00",
            "suma_vat": "23.00",
            "suma_brutto": "123.00",
            "sprzedawca": {
                "nip": "1234567890",
                "nazwa": "Hosting Provider Sp. z o.o.",
                "kraj": "PL"
            },
            "nabywca": {
                "nip": self.profile.nip,
                "nazwa": self.profile.nazwa,
                "kraj": "PL"
            },
            "pozycje": [
                {
                    "opis": "Usługi hostingowe i domena",
                    "ilosc": "1",
                    "cena_jednostkowa_netto": "100.00",
                    "wartosc_netto": "100.00",
                    "stawka_vat": "23",
                    "kwota_vat": "23.00",
                    "wartosc_brutto": "123.00"
                }
            ]
        }
        raw_path = self.raw_dir / "test_google_cloud.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_json_data, f)

        # PreSettlementReview powinien automatycznie uruchomić NonKSeFExtractor
        review = PreSettlementReview.build(self.profile, self.test_rok, self.test_miesiac)
        
        # Sprawdź czy faktura non-ksef znalazła się na liście kosztów
        found = [k for k in review.koszty if k.numer == "TEST-NONKSEF-01"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].zrodlo, "Non-KSeF")
        self.assertEqual(found[0].kwota_netto, Decimal("100.00"))

        # Sprawdź czy w wygenerowanym Markdown pojawił się znacznik Non-KSeF
        md = review.generate_markdown()
        self.assertIn("Non-KSeF", md)
        self.assertIn("TEST-NONKSEF-01", md)

    def test_extract_sales_non_ksef(self):
        # 1. Tworzymy surowy plik sprzedaży spoza KSeF (np. dla klienta zagranicznego)
        raw_sales_data = {
            "invoice_number": "FV-INT-2026/11/01",
            "issue_date": "2026-11-06",
            "customer": {
                "name": "Global Tech Corp Inc.",
                "nip": "9999999999",
                "country": "US"
            },
            "net_amount": "15000.00",
            "vat_amount": "0.00",
            "gross_amount": "15000.00",
            "items": [
                {
                    "description": "Senior Software Engineering Services - November 2026",
                    "net": "15000.00",
                    "vat": "0.00",
                    "gross": "15000.00",
                    "vat_rate": "np"
                }
            ]
        }
        raw_path = self.sales_raw_dir / "test_sales_client.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_sales_data, f)

        # 2. Wywołujemy ekstrakcję
        extracted_files = NonKSeFExtractor.extract_all(self.profile, self.test_rok, self.test_miesiac, force=True)
        self.assertTrue(any(f.name == "test_sales_client.json" for f in extracted_files))

        # 3. Sprawdzamy wyekstrahowany plik w sprzedaz/non-ksef-extracted/
        target_path = self.sales_extracted_dir / "test_sales_client.json"
        self.assertTrue(target_path.exists())

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["numer"], "FV-INT-2026/11/01")
        self.assertEqual(data["typ"], "sprzedaz")
        self.assertEqual(data["zrodlo"], "NON_KSEF")
        self.assertEqual(data["sprzedawca"]["nip"], self.profile.nip)
        self.assertEqual(data["nabywca"]["nip"], "9999999999")
        self.assertEqual(Decimal(data["suma_netto"]), Decimal("15000.00"))

        # 4. Sprawdzamy czy PreSettlementReview uwzględnia tę fakturę w przychodach
        review = PreSettlementReview.build(self.profile, self.test_rok, self.test_miesiac)
        found_sales = [s for s in review.sprzedaz if s.numer == "FV-INT-2026/11/01"]
        self.assertEqual(len(found_sales), 1)
        self.assertEqual(found_sales[0].zrodlo, "Non-KSeF")
        self.assertEqual(found_sales[0].kwota_netto, Decimal("15000.00"))

        # 5. Sprawdzamy czy w tabeli sprzedaży w Markdown widnieje Non-KSeF
        md = review.generate_markdown()
        self.assertIn("FV-INT-2026/11/01", md)
        self.assertIn("📁 Non-KSeF", md)


if __name__ == "__main__":
    unittest.main()
