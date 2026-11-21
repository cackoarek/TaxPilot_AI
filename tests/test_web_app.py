"""
tests/test_web_app.py
Testy integracyjne warstwy webowej FastAPI (Kamień Milowy M1).
"""

import unittest

from fastapi.testclient import TestClient

from src.web.app import app
from src.web.config import COOKIE_ACTIVE_MONTH, COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR


class TestWebApp(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"
        from src.core.company import CompanyProfile
        from tests.fixtures import setup_test_company

        if not CompanyProfile.load_by_nip("7770001122"):
            setup_test_company()

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
        self.assertIn("CloudTech", html)
        self.assertIn("Paczka Przelewów", html)
        self.assertIn("Urząd Skarbowy", html)
        self.assertIn("ZUS", html)

    def test_switch_company(self):
        """Test przełączania firmy przez POST /firmy/switch."""
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn(COOKIE_ACTIVE_NIP, response.cookies)
        self.assertEqual(response.cookies[COOKIE_ACTIVE_NIP], "7770001122")

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

    def test_token_auth_middleware(self):
        """Test opcjonalnej autoryzacji tokenem (NET-1)."""
        import os

        from src.web.config import COOKIE_AUTH_TOKEN

        token_secret = "tajny-token-12345"
        os.environ["TAXPILOT_ACCESS_TOKEN"] = token_secret

        try:
            # 1. Żądanie bez tokenu -> 401 Unauthorized (JSON domyślnie, HTML dla przeglądarki)
            unauth_resp = self.client.get("/")
            self.assertEqual(unauth_resp.status_code, 401)
            self.assertIn("Wymagana autoryzacja", unauth_resp.text)

            unauth_html_resp = self.client.get("/", headers={"Accept": "text/html"})
            self.assertEqual(unauth_html_resp.status_code, 401)
            self.assertIn("Wymagana Autoryzacja", unauth_html_resp.text)

            # 2. Endpoint /health i pliki statyczne są publiczne
            health_resp = self.client.get("/health")
            self.assertEqual(health_resp.status_code, 200)

            # 3. Autoryzacja przez nagłówek Authorization: Bearer <token>
            auth_header_resp = self.client.get("/", headers={"Authorization": f"Bearer {token_secret}"})
            self.assertEqual(auth_header_resp.status_code, 200)

            # 4. Autoryzacja przez parametr query ?token=<token>
            query_resp = self.client.get(f"/?token={token_secret}")
            self.assertEqual(query_resp.status_code, 200)
            self.assertIn(COOKIE_AUTH_TOKEN, query_resp.cookies)

            # 5. Autoryzacja przez ciasteczko
            cookie_client = TestClient(app)
            cookie_client.cookies[COOKIE_AUTH_TOKEN] = token_secret
            cookie_resp = cookie_client.get("/")
            self.assertEqual(cookie_resp.status_code, 200)

            # 6. Błędny token -> 401
            bad_token_resp = self.client.get("/", headers={"Authorization": "Bearer zly_token"})
            self.assertEqual(bad_token_resp.status_code, 401)
        finally:
            del os.environ["TAXPILOT_ACCESS_TOKEN"]


if __name__ == "__main__":
    unittest.main()
