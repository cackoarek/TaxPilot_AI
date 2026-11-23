"""
tests/test_web_app.py
Testy integracyjne warstwy webowej FastAPI (Kamień Milowy M1).
"""

import unittest

from fastapi.testclient import TestClient

from src.web.app import app
from src.web.config import COOKIE_ACTIVE_MONTH, COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR


class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.fixtures import setup_isolated_test_company

        cls.profile = setup_isolated_test_company()

    @classmethod
    def tearDownClass(cls):
        from tests.fixtures import cleanup_test_company

        cleanup_test_company(cls.profile)

    def setUp(self):
        from src.web.app import reset_login_rate_limits

        reset_login_rate_limits()
        self.client = TestClient(app)
        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"

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
        # Weryfikacja poprawnego formatowania rachunków (NRB 2+4*6)
        self.assertIn("PL 80 1010 0071 2222 7770 0011 2200", html)
        self.assertIn("PL 50 1010 1023 0000 2677 7000 1122", html)
        # Zabezpieczenie przed starym, wadliwym formatem
        self.assertNotIn("7770001122 000", html)
        self.assertNotIn("2613 9510 0000", html)

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

            # 4. Autoryzacja przez parametr query ?token=<token> ze stripowaniem tokena (303 Redirect - SEC-3)
            query_resp = self.client.get(f"/?token={token_secret}", follow_redirects=False)
            self.assertEqual(query_resp.status_code, 303)
            self.assertEqual(query_resp.headers["location"], "http://testserver/")
            self.assertIn(COOKIE_AUTH_TOKEN, query_resp.cookies)

            # Następne żądanie klienta z zapisanym ciasteczkiem przechodzi z kodem 200
            self.client.cookies[COOKIE_AUTH_TOKEN] = token_secret
            next_resp = self.client.get("/")
            self.assertEqual(next_resp.status_code, 200)

            # 4b. Logowanie przez POST /login (SEC-3)
            login_client = TestClient(app)
            login_resp = login_client.post("/login", data={"token": token_secret}, follow_redirects=False)
            self.assertEqual(login_resp.status_code, 303)
            self.assertIn(COOKIE_AUTH_TOKEN, login_resp.cookies)

            # Błędny token w POST /login -> 401
            from unittest.mock import patch

            with patch("src.web.app.time.sleep"):
                bad_login = login_client.post("/login", data={"token": "zly-token"})
                self.assertEqual(bad_login.status_code, 401)

            # 4c. Wylogowanie przez GET /logout
            logout_resp = login_client.get("/logout", follow_redirects=False)
            self.assertEqual(logout_resp.status_code, 303)

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
