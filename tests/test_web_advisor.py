"""
tests/test_web_advisor.py
Testy integracyjne modułu Doradcy Podatkowego i Symulatora Form Opodatkowania (Kamień Milowy M6).
"""
import unittest
from fastapi.testclient import TestClient

from src.web.app import app


class TestWebAdvisor(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP
        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"
        from src.core.company import CompanyProfile
        from tests.fixtures import setup_test_company
        if not CompanyProfile.load_by_nip("7770001122"):
            setup_test_company()

    def test_advisor_dashboard_renders(self):
        """Test renderowania strony głównej doradcy podatkowego GET /doradca."""
        response = self.client.get("/doradca")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Sprawdzenie obecności kluczowych sekcji doradcy
        self.assertIn("Doradca Podatkowy", html)
        self.assertIn("Parametry Symulacji Rocznej", html)
        self.assertIn("Ryczałt ewidencjonowany", html)
        self.assertIn("Podatek Liniowy 19%", html)
        self.assertIn("Skala Podatkowa", html)
        self.assertIn("Najkorzystniejsza Forma", html)
        self.assertIn("Audyt Brakujących Kosztów", html)

    def test_simulate_endpoint_ryczalt_optimum(self):
        """Test symulacji HTMX przy niskich kosztach (gdzie optymalny jest ryczałt)."""
        response = self.client.post(
            "/api/advisor/simulate",
            data={
                "przychod": "300000",
                "koszt": "20000",
                "stawka_ryczaltu": "0.12",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("simulation-result", html)
        self.assertIn("Najkorzystniejsza Forma", html)
        self.assertIn("Ryczałt ewidencjonowany", html)
        self.assertIn("Optimum", html)
        self.assertIn("Dochód na rękę rocznie", html)

    def test_simulate_endpoint_liniowy_optimum_at_high_costs(self):
        """Test symulacji HTMX przy bardzo wysokich kosztach (gdzie ryczałt przestaje być opłacalny)."""
        response = self.client.post(
            "/api/advisor/simulate",
            data={
                "przychod": "300000",
                "koszt": "250000",  # Bardzo wysokie koszty 250k na 300k przychodu
                "stawka_ryczaltu": "0.12",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("simulation-result", html)
        # Przy wysokich kosztach wygrywa Liniowy lub Skala (ponieważ ryczałt płaci się od całości przychodu 300k)
        self.assertTrue("Podatek Liniowy 19%" in html or "Skala Podatkowa" in html)

    def test_annual_financial_summary_and_extrapolation_elements(self):
        """Test czy widok /doradca poprawnie ładuje dane roczne i przycisk ekstrapolacji."""
        response = self.client.get("/doradca")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Sprawdzenie elementów nowego paska informacyjnego i przycisków
        self.assertIn("Rzeczywiste dane firmy za rok", html)
        self.assertIn("Zasymuluj pełny rok", html)
        self.assertIn("Przewodnik: Doradca Podatkowy", html)

    def test_advisor_annual_fallback_previous_year(self):
        """Test fallbacku do poprzedniego roku gdy styczeń/rok bez danych."""
        from pathlib import Path
        p_path = Path("firmy/7770001122-CloudTech_Solutions_Jan_Kowalski")
        if not (p_path / "rozliczenia" / "2026").exists():
            self.skipTest("Brak danych rocznych 2026 dla firmy testowej")
        from src.core.company import CompanyProfile
        from src.skills.tax_advisor_tools import get_annual_financial_summary

        profile = CompanyProfile.load_from_dir(p_path)
        
        # Test roku 2026 (gdzie są dane z 11 miesięcy)
        summary_2026 = get_annual_financial_summary(profile, "2026", "10")
        self.assertEqual(summary_2026["rok"], "2026")
        self.assertGreater(summary_2026["actual_przychod"], 0)
        self.assertTrue(summary_2026["can_extrapolate"])

        # Test stycznia dla roku 2027 (gdzie brak danych - fallback do 2026)
        summary_2027 = get_annual_financial_summary(profile, "2027", "01")
        self.assertTrue(summary_2027["is_fallback_prev_year"])
        self.assertEqual(summary_2027["source_year"], "2026")
        self.assertEqual(summary_2027["actual_przychod"], summary_2026["actual_przychod"])


if __name__ == "__main__":
    unittest.main()
