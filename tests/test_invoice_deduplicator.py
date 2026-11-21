"""
Testy jednostkowe silnika deduplikacji faktur i wykrywania kolizji źródłowych (InvoiceDeduplicator).
Weryfikuje ochronę przed:
1. Kolizją KSeF vs Non-KSeF (KSeF First - gdy faktura pobrana z KSeF zostanie powtórnie wgrana jako PDF)
2. Duplikatami międzyokresowymi (Cross-Month Deduplication - gdy dokument z m-ca M wgrano w m-cu M+1)
3. Zdublowanymi plikami w tym samym miesiącu (Same-Period Duplicate)
"""

import unittest
from decimal import Decimal
from pathlib import Path
import json

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType, InvoiceParty, InvoiceItem
from src.level_1_ingestion.invoice_deduplicator import (
    InvoiceDeduplicator,
    DuplicateType,
    DuplicateAnomaly,
    normalize_invoice_number,
    extract_core_number,
    clean_nip,
)
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.skills.pre_settlement_review import PreSettlementReview
from src.level_3_tax_settlement.settlement_service import SettlementService
from tests.fixtures import setup_test_company, cleanup_test_company, TEST_NIP, TEST_NAME


class TestInvoiceDeduplicator(unittest.TestCase):

    def setUp(self):
        self.profile = setup_test_company()
        self.assertIsNotNone(self.profile)

    def tearDown(self):
        cleanup_test_company(self.profile)

    def test_normalization_and_core_number(self):
        """Testuje normalizację numerów faktur i NIP-ów."""
        self.assertEqual(normalize_invoice_number("FV/123/2026"), "FV1232026")
        self.assertEqual(normalize_invoice_number("  f-12 3 / abc "), "F123ABC")
        self.assertEqual(extract_core_number("FV/36230/1561/26"), "36230156126")
        self.assertEqual(extract_core_number("FAKTURA-VAT 999/2026"), "9992026")
        self.assertEqual(clean_nip("PL 777-000-11-22"), "7770001122")
        self.assertEqual(clean_nip("IE6388047V"), "IE6388047V")

    def test_are_invoices_matching(self):
        """Testuje kryteria dopasowania faktur reprezentujących to samo zdarzenie."""
        seller = InvoiceParty(nip="5213242793", nazwa="T-Mobile Polska S.A.")
        buyer = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME)

        inv1 = Invoice(
            numer="FV/100/2026",
            data_wystawienia="2026-04-15",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
            typ=InvoiceType.KOSZT,
        )

        # Identyczny numer, inny format zapisu (np. myślniki zamiast ukośników)
        inv2 = Invoice(
            numer="100-2026",
            data_wystawienia="2026-04-15",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
            typ=InvoiceType.KOSZT,
        )

        match, reason = InvoiceDeduplicator.are_invoices_matching(inv1, inv2)
        self.assertTrue(match)
        self.assertIn("Identyczny numer faktury", reason)

        # Dopasowanie po kwotach i dacie przy braku/innej numeracji (np. paragon)
        inv_paragon_ksef = Invoice(
            numer="KSEF-PAR-1",
            data_wystawienia="2026-04-10",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("45.50"),
            suma_vat=Decimal("10.47"),
            suma_brutto=Decimal("55.97"),
            typ=InvoiceType.KOSZT,
        )
        inv_paragon_pdf = Invoice(
            numer="paragon_10_04.pdf",
            data_wystawienia="2026-04-10",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("45.50"),
            suma_vat=Decimal("10.47"),
            suma_brutto=Decimal("55.97"),
            typ=InvoiceType.KOSZT,
        )
        match_p, reason_p = InvoiceDeduplicator.are_invoices_matching(inv_paragon_ksef, inv_paragon_pdf)
        self.assertTrue(match_p)
        self.assertIn("Identyczny kontrahent", reason_p)

    def test_ksef_collision_same_month(self):
        """
        Scenariusz 1: Faktura pobrana z KSeF oraz równocześnie wgrana jako pobrany PDF do non-ksef.
        KSeF ma bezwzględny priorytet; plik non-ksef musi zostać wykluczony, a anomalia zgłoszona.
        """
        seller = InvoiceParty(nip="5213242793", nazwa="T-Mobile Polska S.A.")
        buyer = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME)

        # 1. Zapisujemy fakturę w KSeF
        inv_ksef = Invoice(
            numer="F/2026/04/001",
            data_wystawienia="2026-04-15",
            data_sprzedazy="2026-04-15",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("200.00"),
            suma_vat=Decimal("46.00"),
            suma_brutto=Decimal("246.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="KSEF",
            plik_zrodlowy="ksef_20260415_001.xml",
        )
        InvoiceStorage.save_invoice(self.profile, inv_ksef)

        # 2. Użytkownik wgrał ten sam dokument jako pobrany PDF do non-ksef-raw (ekstrahowany do non-ksef-extracted)
        inv_pdf = Invoice(
            numer="F/2026/04/001",
            data_wystawienia="2026-04-15",
            data_sprzedazy="2026-04-15",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("200.00"),
            suma_vat=Decimal("46.00"),
            suma_brutto=Decimal("246.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="tmobile_faktura_kwiecien.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile, inv_pdf, typ=InvoiceType.KOSZT, raw_source_name="tmobile_faktura_kwiecien.pdf"
        )

        # 3. Przeprowadzamy deduplikację
        clean_invs, anomalies = InvoiceDeduplicator.deduplicate_month(
            self.profile, "2026", "04", typ=InvoiceType.KOSZT
        )

        # Sprawdzenie: faktura F/2026/04/001 występuje tylko RAZ w clean_invs ze źródłem KSeF
        matching_clean = [i for i in clean_invs if i.numer == "F/2026/04/001"]
        self.assertEqual(len(matching_clean), 1)
        self.assertEqual(matching_clean[0].zrodlo, "KSEF")

        # Sprawdzenie: anomalia KSEF_COLLISION została zarejestrowana
        ksef_collisions = [a for a in anomalies if a.typ_duplikatu == DuplicateType.KSEF_COLLISION]
        self.assertEqual(len(ksef_collisions), 1)
        self.assertEqual(ksef_collisions[0].plik_zrodlowy_odrzucony, "tmobile_faktura_kwiecien.pdf")
        self.assertIn("została oficjalnie pobrana z KSeF", ksef_collisions[0].opis_problemu)

    def test_cross_month_duplicate(self):
        """
        Scenariusz 2: Faktura wgrana powtórnie w innym miesiącu.
        Faktura istnieje w 2026-04, a użytkownik ponownie wrzucił ten sam plik w 2026-05.
        """
        seller = InvoiceParty(nip="5252545285", nazwa="Google Cloud Ireland")
        buyer = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME)

        # 1. Zapisujemy fakturę w kwietniu (2026-04)
        inv_april = Invoice(
            numer="GCP-2026-04-99",
            data_wystawienia="2026-04-30",
            data_sprzedazy="2026-04-30",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("350.00"),
            suma_vat=Decimal("80.50"),
            suma_brutto=Decimal("430.50"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="google_cloud_april.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile, inv_april, typ=InvoiceType.KOSZT, raw_source_name="google_cloud_april.pdf"
        )

        # 2. Użytkownik omyłkowo wgrał ten sam dokument w maju (2026-05)
        inv_may_duplicate = Invoice(
            numer="GCP-2026-04-99",
            data_wystawienia="2026-04-30",
            data_sprzedazy="2026-04-30",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("350.00"),
            suma_vat=Decimal("80.50"),
            suma_brutto=Decimal("430.50"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="google_cloud_may_copy.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile,
            inv_may_duplicate,
            typ=InvoiceType.KOSZT,
            raw_source_name="google_cloud_may_copy.pdf",
            target_rok="2026",
            target_miesiac="05",
        )

        # 3. Sprawdzamy deduplikację dla maja (2026-05)
        clean_invs_may, anomalies_may = InvoiceDeduplicator.deduplicate_month(
            self.profile, "2026", "05", typ=InvoiceType.KOSZT
        )

        # Powtórzona faktura NIE MOŻE wejść do rozliczenia maja
        matching_clean_may = [i for i in clean_invs_may if i.numer == "GCP-2026-04-99"]
        self.assertEqual(len(matching_clean_may), 0)

        # Anomalia CROSS_MONTH_DUPLICATE musi być zgłoszona
        cross_anomalies = [a for a in anomalies_may if a.typ_duplikatu == DuplicateType.CROSS_MONTH_DUPLICATE]
        self.assertEqual(len(cross_anomalies), 1)
        self.assertEqual(cross_anomalies[0].miesiac_pierwotny, "04")
        self.assertEqual(cross_anomalies[0].rok_pierwotny, "2026")
        self.assertIn("została już uprzednio zaksięgowana w miesiącu 2026-04", cross_anomalies[0].opis_problemu)

    def test_same_period_non_ksef_duplicate(self):
        """
        Scenariusz 3: Wielokrotne wgranie tego samego pliku w tym samym miesiącu.
        """
        seller = InvoiceParty(nip="1112223344", nazwa="Sklep Komputerowy")
        buyer = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME)

        inv1 = Invoice(
            numer="SK/888/2026",
            data_wystawienia="2026-04-20",
            data_sprzedazy="2026-04-20",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("500.00"),
            suma_vat=Decimal("115.00"),
            suma_brutto=Decimal("615.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="myszka_klawiatura.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile, inv1, typ=InvoiceType.KOSZT, raw_source_name="myszka_klawiatura.pdf"
        )

        inv2 = Invoice(
            numer="SK/888/2026",
            data_wystawienia="2026-04-20",
            data_sprzedazy="2026-04-20",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("500.00"),
            suma_vat=Decimal("115.00"),
            suma_brutto=Decimal("615.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="myszka_klawiatura_kopia.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile, inv2, typ=InvoiceType.KOSZT, raw_source_name="myszka_klawiatura_kopia.pdf"
        )

        clean_invs, anomalies = InvoiceDeduplicator.deduplicate_month(
            self.profile, "2026", "04", typ=InvoiceType.KOSZT
        )

        matching_clean = [i for i in clean_invs if i.numer == "SK/888/2026"]
        self.assertEqual(len(matching_clean), 1)

        same_period = [a for a in anomalies if a.typ_duplikatu == DuplicateType.SAME_PERIOD_DUPLICATE]
        self.assertEqual(len(same_period), 1)
        self.assertIn("została wgrana wielokrotnie w tym samym miesiącu", same_period[0].opis_problemu)

    def test_review_and_settlement_reporting(self):
        """
        Weryfikuje, czy PreSettlementReview oraz SettlementService poprawnie
        prezentują wykryte duplikaty w wygenerowanych dokumentach markdown.
        """
        seller = InvoiceParty(nip="5213242793", nazwa="T-Mobile Polska S.A.")
        buyer = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME)

        # Tworzymy kolizję KSeF vs Non-KSeF
        inv_ksef = Invoice(
            numer="F/COLLISION/01",
            data_wystawienia="2026-04-12",
            data_sprzedazy="2026-04-12",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="KSEF",
            plik_zrodlowy="ksef_collision_01.xml",
        )
        InvoiceStorage.save_invoice(self.profile, inv_ksef)

        inv_pdf = Invoice(
            numer="F/COLLISION/01",
            data_wystawienia="2026-04-12",
            data_sprzedazy="2026-04-12",
            sprzedawca=seller,
            nabywca=buyer,
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            plik_zrodlowy="duplicate_upload.pdf",
        )
        InvoiceStorage.save_non_ksef_invoice(
            self.profile, inv_pdf, typ=InvoiceType.KOSZT, raw_source_name="duplicate_upload.pdf"
        )

        # 1. Sprawdzamy PreSettlementReview
        review = PreSettlementReview.build(self.profile, "2026", "04")
        self.assertTrue(len(review.duplikaty) >= 1)
        review_md = review.generate_markdown()
        self.assertIn("## 🚨 0. Wykryte Duplikaty Dokumentów", review_md)
        self.assertIn("KSeF First (kolizja z KSeF)", review_md)
        self.assertIn("duplicate_upload.pdf", review_md)

        # 2. Sprawdzamy SettlementService
        settlement = SettlementService.settle_month(self.profile, "2026", "04", zapisz_raporty=True)
        self.assertTrue(len(settlement.ledger.duplikaty) >= 1)

        settlement_dir = self.profile.katalog_firmy / "rozliczenia" / "2026" / "04"
        with open(settlement_dir / "rozliczenie.md", "r", encoding="utf-8") as f:
            rozliczenie_md = f.read()
        self.assertIn("Wykryte i Zneutralizowane Duplikaty Dokumentów", rozliczenie_md)

        with open(settlement_dir / "sprawozdanie.md", "r", encoding="utf-8") as f:
            sprawozdanie_md = f.read()
        self.assertIn("Część IV: Rejestr Wykrytych Duplikatów i Kolizji Źródłowych", sprawozdanie_md)
        self.assertIn("Kolizja KSeF vs Non-KSeF", sprawozdanie_md)


if __name__ == "__main__":
    unittest.main()
