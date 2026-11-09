"""
Testy jednostkowe modułu KSeF Parser oraz Invoice Storage.
"""

import shutil
import unittest
from decimal import Decimal
from pathlib import Path

from src.core.company import CompanyProfile, KSeFConfig
from src.core.invoice import InvoiceType
from src.level_1_ingestion.ksef_parser import KSeFParser
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.config import TESTS_DIR, BASE_DIR


class TestKSeFParserAndStorage(unittest.TestCase):

    def setUp(self):
        self.profile = CompanyProfile(
            nip="7770001122",
            nazwa="CloudTech Solutions Jan Kowalski",
            katalog_nazwa="7770001122-CloudTech_Solutions_Jan_Kowalski",
            ksef=KSeFConfig(srodowisko="TEST", token="0261108-EC-TEST-TOKEN|nip-7770001122|abcdef1234567890"),
        )

        self.samples_dir = TESTS_DIR / "sample_ksef_invoices"
        self.sprzedaz_xml_path = self.samples_dir / "sample_sprzedaz_fa2.xml"
        self.koszt_xml_path = self.samples_dir / "sample_koszt_fa2.xml"

    def tearDown(self):
        test_dir = self.profile.katalog_firmy
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_parse_sprzedaz(self):
        with open(self.sprzedaz_xml_path, "r", encoding="utf-8") as f:
            xml_content = f.read()

        invoice = KSeFParser.parse_xml(xml_content, target_company_nip=self.profile.nip)

        self.assertEqual(invoice.typ, InvoiceType.SPRZEDAZ)
        self.assertEqual(invoice.numer, "FV/2026/01/001")
        self.assertEqual(invoice.sprzedawca.nip, "7770001122")
        self.assertEqual(invoice.nabywca.nip, "5250000000")
        self.assertEqual(invoice.suma_netto, Decimal("15000.00"))
        self.assertEqual(invoice.suma_vat, Decimal("3450.00"))
        self.assertEqual(invoice.suma_brutto, Decimal("18450.00"))
        self.assertEqual(len(invoice.pozycje), 1)
        self.assertIn("Usługi programistyczne", invoice.pozycje[0].opis)
        self.assertEqual(invoice.rok, "2026")
        self.assertEqual(invoice.miesiac, "01")

    def test_parse_koszt(self):
        with open(self.koszt_xml_path, "r", encoding="utf-8") as f:
            xml_content = f.read()

        invoice = KSeFParser.parse_xml(xml_content, target_company_nip=self.profile.nip)

        self.assertEqual(invoice.typ, InvoiceType.KOSZT)
        self.assertEqual(invoice.numer, "FV/CLOUD/2026/01/99")
        self.assertEqual(invoice.sprzedawca.nip, "1234567890")
        self.assertEqual(invoice.nabywca.nip, "7770001122")
        self.assertEqual(invoice.suma_netto, Decimal("600.00"))
        self.assertEqual(invoice.suma_vat, Decimal("138.00"))
        self.assertEqual(invoice.suma_brutto, Decimal("738.00"))

    def test_invoice_storage(self):
        # Parsujemy i zapisujemy obie faktury do katalogu firmy
        with open(self.sprzedaz_xml_path, "r", encoding="utf-8") as f:
            inv_sprzedaz = KSeFParser.parse_xml(f.read(), target_company_nip=self.profile.nip)
        
        with open(self.koszt_xml_path, "r", encoding="utf-8") as f:
            inv_koszt = KSeFParser.parse_xml(f.read(), target_company_nip=self.profile.nip)

        json_s, xml_s = InvoiceStorage.save_invoice(self.profile, inv_sprzedaz)
        json_k, xml_k = InvoiceStorage.save_invoice(self.profile, inv_koszt)

        self.assertTrue(json_s.exists())
        self.assertTrue(xml_s.exists())
        self.assertTrue(json_k.exists())
        self.assertTrue(xml_k.exists())

        # Sprawdź pobieranie listy faktur za styczeń 2026
        invoices = InvoiceStorage.list_invoices(self.profile, "2026", "01")
        self.assertEqual(len(invoices), 2)

    def test_ksef_token_in_profile(self):
        from src.level_1_ingestion.ksef_client import KSeFClient
        client = KSeFClient(self.profile)
        self.assertTrue(client.is_token_configured())
        token = client.get_auth_token()
        self.assertIsNotNone(token)
        self.assertTrue(token.startswith("0261108-EC"))
        self.assertEqual(self.profile.ksef.srodowisko, "TEST")


if __name__ == "__main__":
    unittest.main()
