"""
tests/test_web_app.py
Testy integracyjne warstwy webowej FastAPI (Kamień Milowy M1).
"""
import unittest
from fastapi.testclient import TestClient
from src.web.app import app
from src.web.config import COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR, COOKIE_ACTIVE_MONTH


class TestWebApp(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        """Test endpointu /health."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "TaxPilot AI")

    def test_dashboard_renders(self):
        """Test renderowania strony głównej / z szablonem Jinja2."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        # Sprawdzenie obecności kluczowych elementów interfejsu
        self.assertIn("TaxPilot", html)
        self.assertIn("Smart IT Solutions", html)
        self.assertIn("Paczka Przelewów", html)
        self.assertIn("Urząd Skarbowy", html)
        self.assertIn("ZUS", html)

    def test_switch_company(self):
        """Test przełączania firmy przez POST /firmy/switch."""
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "5322030067", "redirect_url": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn(COOKIE_ACTIVE_NIP, response.cookies)
        self.assertEqual(response.cookies[COOKIE_ACTIVE_NIP], "5322030067")

    def test_switch_period(self):
        """Test przełączania okresu przez POST /firmy/period."""
        response = self.client.post(
            "/firmy/period",
            data={"rok": "2026", "miesiac": "02", "redirect_url": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.cookies[COOKIE_ACTIVE_YEAR], "2026")
        self.assertEqual(response.cookies[COOKIE_ACTIVE_MONTH], "02")

    def test_static_files_served(self):
        """Test serwowania plików statycznych CSS i JS."""
        css_resp = self.client.get("/static/css/custom.css")
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn("htmx-indicator", css_resp.text)

        htmx_resp = self.client.get("/static/js/htmx.min.js")
        self.assertEqual(htmx_resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
