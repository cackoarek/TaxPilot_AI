"""
tests/test_web_aml.py
Testy integracyjne modułu AML i Białej Listy VAT (Kamień Milowy M2).
"""
import unittest
from unittest.mock import patch
from decimal import Decimal
from fastapi.testclient import TestClient

from src.web.app import app
from src.skills.aml_tools import (
    AMLVerificationEngine,
    KartaWeryfikacjiKontrahenta,
    PoziomRyzykaAML,
    DecyzjaWspolpracy,
)


class TestWebAML(unittest.TestCase):
    def setUp(self):
        AMLVerificationEngine.clear_cache()
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP
        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"
        from src.core.company import CompanyProfile
        from tests.fixtures import setup_test_company
        if not CompanyProfile.load_by_nip("7770001122"):
            setup_test_company()

    def test_aml_dashboard_view(self):
        """Test widoku GET /aml."""
        response = self.client.get("/aml")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Centrum Compliance", html)
        self.assertIn("Biała Lista VAT", html)
        self.assertIn("Szybka Weryfikacja Ad-Hoc", html)
        self.assertIn("KROK 3", html)
        self.assertIn("/ksiegowanie", html)
        self.assertIn("Przejdź do Kroku 4: Księgowanie", html)
        self.assertTrue("5252545285" in html or "5213242793" in html or "Kontrahent" in html)

    def test_adhoc_verification_post(self):
        """Test POST /aml/verify dla NIP 5252545285."""
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5252545285",
                "nazwa": "KAFT SP. Z O.O.",
                "regon": "146476100",
                "adres": "ul. Testowa 1, 00-001 Warszawa",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["42109010560000000136468977"],
            }
            response = self.client.post(
                "/aml/verify",
                data={
                    "nip": "5252545285",
                    "rachunek": "42109010560000000136468977",
                    "kwota": "42607.20",
                    "force": "false",
                },
            )
            self.assertEqual(response.status_code, 200)
            html = response.text
            self.assertIn("5252545285", html)
            self.assertIn("NISKIE RYZYKO", html)
            self.assertIn("Płatnik VAT Czynny", html)
            self.assertIn("Kryptograficzny dowód SHA-256", html)

    def test_adhoc_verification_offline_handling(self):
        """Test obsługi błędu sieci (blad_polaczenia=True) i wyświetlenia banera ostrzegawczego."""
        offline_karta = KartaWeryfikacjiKontrahenta(
            nip="9998887766",
            nazwa="Firma Testowa Offline Sp. z o.o.",
            adres="ul. Prosta 1, 00-001 Warszawa",
            status_vat="Brak połączenia z API MF (błąd sieci / offline)",
            platnik_vat_czynny=False,
            poziom_ryzyka=PoziomRyzykaAML.SREDNIE,
            decyzja=DecyzjaWspolpracy.WYMAGA_WYJASNIENIA,
            uzasadnienie_decyzji="Brak możliwości potwierdzenia statusu podatnika VAT z powodu awarii sieci.",
            blad_polaczenia=True,
            komunikat_bledu="Connection timeout to mf.gov.pl",
        )

        with patch("src.skills.aml_tools.AMLVerificationEngine.verify_contractor", return_value=offline_karta):
            response = self.client.post("/aml/verify", data={"nip": "9998887766"})
            self.assertEqual(response.status_code, 200)
            html = response.text
            self.assertIn("UWAGA: RAPORT NIEKOMPLETNY Z POWODU BRAKU POŁĄCZENIA", html)
            self.assertIn("nie zatwierdzaj płatności ani rozliczenia", html)
            self.assertIn("--force", html)

    def test_download_contractor_card_pdf(self):
        """Test pobierania karty weryfikacji PDF."""
        response = self.client.get("/aml/karta/pdf/5252545285?rok=2026&miesiac=01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(len(response.content) > 1000)

    def test_download_monthly_report_pdf(self):
        """Test pobierania zbiorczego raportu PDF."""
        response = self.client.get("/aml/raport/pdf?rok=2026&miesiac=01")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(len(response.content) > 1000)

    def test_download_monthly_report_md(self):
        """Test pobierania zbiorczego raportu Markdown."""
        response = self.client.get("/aml/raport/md?rok=2026&miesiac=01")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers["content-type"])
        self.assertIn("Zbiorczy Raport Weryfikacji", response.text)


if __name__ == "__main__":
    unittest.main()
