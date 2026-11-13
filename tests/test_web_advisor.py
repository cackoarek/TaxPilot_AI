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


if __name__ == "__main__":
    unittest.main()
