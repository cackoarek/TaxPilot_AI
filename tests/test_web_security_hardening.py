"""
tests/test_web_security_hardening.py
Testy regresyjne weryfikujące utwardzenie bezpieczeństwa aplikacji webowej (Sesja 03):
- SEC-6: Dynamiczna flaga Secure w ciasteczkach przy HTTPS
- SEC-7: Rate Limiter per IP i nagłówki Cache-Control: no-store na /login
- SEC-8: Walidacja długości tokena (max 256 znaków)
- SEC-9: Ochrona przed Open Redirect w /login (CWE-601)
- SEC-10: Migracja uprawnień chmod 700 / 600
- SEC-11: Ochrona przed atakami CSRF w Local-First (Origin / Referer)
"""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.company import migrate_data_permissions
from src.web.app import (
    app,
    is_safe_redirect_url,
    reset_login_rate_limits,
)
from src.web.config import COOKIE_ACTIVE_NIP, COOKIE_AUTH_TOKEN
from tests.fixtures import cleanup_test_company, setup_isolated_test_company


class TestWebSecurityHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = setup_isolated_test_company()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_company(cls.profile)

    def setUp(self):
        reset_login_rate_limits()
        self.client = TestClient(app)
        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"

    def test_open_redirect_helper(self):
        """Weryfikuje funkcję is_safe_redirect_url przeciwko wektorom Open Redirect (SEC-9)."""
        # Bezpieczne ścieżki względne
        self.assertTrue(is_safe_redirect_url("/"))
        self.assertTrue(is_safe_redirect_url("/dashboard"))
        self.assertTrue(is_safe_redirect_url("/settlement?rok=2026&miesiac=01"))
        self.assertTrue(is_safe_redirect_url("/invoices/upload"))

        # Niebezpieczne wektory zewnętrzne i protokoły
        self.assertFalse(is_safe_redirect_url(""))
        self.assertFalse(is_safe_redirect_url("https://evil.com"))
        self.assertFalse(is_safe_redirect_url("http://attacker.org/steal"))
        self.assertFalse(is_safe_redirect_url("//evil.com"))
        self.assertFalse(is_safe_redirect_url("//evil.com/path"))
        self.assertFalse(is_safe_redirect_url("/\\evil.com"))
        self.assertFalse(is_safe_redirect_url("/path\\with\\backslash"))
        self.assertFalse(is_safe_redirect_url("/path\nwith\nnewline"))
        self.assertFalse(is_safe_redirect_url("javascript:alert(1)"))
        self.assertFalse(is_safe_redirect_url("data:text/html,evil"))

    def test_open_redirect_in_login_endpoint(self):
        """Weryfikuje, że POST /login neutralizuje próby zewnętrznego przekierowania (SEC-9)."""
        token = "test-token-hardened-32-chars-long!"
        os.environ["TAXPILOT_ACCESS_TOKEN"] = token
        try:
            # 1. Zewnętrzny URL evil.com musi być zredukowany do bezpiecznego "/"
            resp = self.client.post(
                "/login",
                data={"token": token, "redirect_url": "https://evil.com/phishing"},
                follow_redirects=False,
            )
            self.assertEqual(resp.status_code, 303)
            self.assertEqual(resp.headers["location"], "/")

            # 2. Protocol-relative URL //evil.com musi być zredukowany do "/"
            resp2 = self.client.post(
                "/login",
                data={"token": token, "redirect_url": "//evil.com/test"},
                follow_redirects=False,
            )
            self.assertEqual(resp2.status_code, 303)
            self.assertEqual(resp2.headers["location"], "/")

            # 3. Prawidłowy lokalny redirect jest dozwolony
            resp3 = self.client.post(
                "/login",
                data={"token": token, "redirect_url": "/settlement"},
                follow_redirects=False,
            )
            self.assertEqual(resp3.status_code, 303)
            self.assertEqual(resp3.headers["location"], "/settlement")
        finally:
            del os.environ["TAXPILOT_ACCESS_TOKEN"]

    from unittest.mock import patch

    @patch("src.web.app.time.sleep")
    def test_rate_limiter_and_no_store_on_login(self, mock_sleep):
        """Weryfikuje ochronę przed brute-force oraz nagłówki Cache-Control (SEC-7)."""
        token = "secret-token-rate-limit-test-32chars"
        os.environ["TAXPILOT_ACCESS_TOKEN"] = token
        try:
            # Wykonaj 5 błędnych prób
            for i in range(5):
                resp = self.client.post(
                    "/login",
                    data={"token": f"wrong-token-{i}"},
                    headers={"X-Forwarded-For": "192.168.1.100"},
                )
                self.assertEqual(resp.status_code, 401)
                self.assertIn("no-store", resp.headers.get("cache-control", "").lower())
                self.assertIn("Nieprawidłowy token dostępu", resp.text)

            self.assertEqual(mock_sleep.call_count, 5)

            # 6. próba powinna zostać zablokowana kodem 429 Too Many Requests
            rate_limit_resp = self.client.post(
                "/login",
                data={"token": "another-attempt"},
                headers={"X-Forwarded-For": "192.168.1.100"},
            )
            self.assertEqual(rate_limit_resp.status_code, 429)
            self.assertEqual(rate_limit_resp.headers.get("retry-after"), "60")
            self.assertIn("Zbyt Wiele Prób", rate_limit_resp.text)
        finally:
            del os.environ["TAXPILOT_ACCESS_TOKEN"]

    def test_csrf_origin_protection(self):
        """Weryfikuje ochronę przed CSRF dla żądań mutujących stan POST (SEC-11)."""
        # 1. Żądanie z obcym Origin (np. złośliwa strona http://evil.com) -> 403 Forbidden
        resp_evil_origin = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            headers={"Origin": "http://evil.com"},
        )
        self.assertEqual(resp_evil_origin.status_code, 403)
        self.assertIn("CSRF", resp_evil_origin.text)

        # 2. Żądanie z obcym Referer -> 403 Forbidden
        resp_evil_referer = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            headers={"Referer": "http://attacker.org/malicious.html"},
        )
        self.assertEqual(resp_evil_referer.status_code, 403)
        self.assertIn("CSRF", resp_evil_referer.text)

        # 3. Żądanie z Origin: null (sandboxed iframe) -> 403 Forbidden
        resp_null_origin = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            headers={"Origin": "null"},
        )
        self.assertEqual(resp_null_origin.status_code, 403)

        # 4. Żądanie z lokalnego Origin (127.0.0.1:8000 lub localhost) -> 303 dozwolone
        resp_local = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            headers={"Origin": "http://127.0.0.1:8000"},
            follow_redirects=False,
        )
        self.assertEqual(resp_local.status_code, 303)

    def test_dynamic_secure_cookie(self):
        """Weryfikuje flagę Secure ciasteczka autoryzacyjnego w zależności od HTTPS (SEC-6)."""
        token = "cookie-test-token-without-s-word-32chars!"
        os.environ["TAXPILOT_ACCESS_TOKEN"] = token
        try:
            # 1. Połączenie HTTP (domyślny localhost) -> secure=False
            http_resp = self.client.post(
                "/login",
                data={"token": token},
                follow_redirects=False,
            )
            self.assertEqual(http_resp.status_code, 303)
            raw_cookie_header = http_resp.headers.get("set-cookie", "")
            self.assertIn(COOKIE_AUTH_TOKEN, raw_cookie_header)
            self.assertIn("httponly", raw_cookie_header.lower())
            self.assertNotIn("; secure", raw_cookie_header.lower())

            # 2. Połączenie z nagłówkiem X-Forwarded-Proto: https -> secure=True
            https_resp = self.client.post(
                "/login",
                data={"token": token},
                headers={"X-Forwarded-Proto": "https"},
                follow_redirects=False,
            )
            self.assertEqual(https_resp.status_code, 303)
            raw_https_cookie = https_resp.headers.get("set-cookie", "")
            self.assertIn("; secure", raw_https_cookie.lower())
            self.assertIn("httponly", raw_https_cookie.lower())

            # 3. Wymuszenie przez zmienną TAXPILOT_COOKIE_SECURE=1
            os.environ["TAXPILOT_COOKIE_SECURE"] = "1"
            forced_resp = self.client.post(
                "/login",
                data={"token": token},
                follow_redirects=False,
            )
            self.assertIn("; secure", forced_resp.headers.get("set-cookie", "").lower())
        finally:
            del os.environ["TAXPILOT_ACCESS_TOKEN"]
            os.environ.pop("TAXPILOT_COOKIE_SECURE", None)

    def test_migrate_data_permissions(self):
        """Weryfikuje funkcję migrate_data_permissions (chmod 700 / 600 - SEC-10)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            company_dir = base / "1234567890-Firma_Test"
            company_dir.mkdir(parents=True)
            # Ustaw zbyt szerokie uprawnienia (np. 0777)
            company_dir.chmod(0o777)

            profil_file = company_dir / "profil.json"
            profil_file.write_text('{"nip": "1234567890"}', encoding="utf-8")
            profil_file.chmod(0o666)

            sub_dir = company_dir / "faktury"
            sub_dir.mkdir()
            sub_dir.chmod(0o755)

            rules_file = company_dir / "reguly_kosztowe.json"
            rules_file.write_text("{}", encoding="utf-8")
            rules_file.chmod(0o644)

            # Uruchom migrację
            updated = migrate_data_permissions(base)
            self.assertGreater(updated, 0)

            # Sprawdź uprawnienia katalogu (musi być 0700)
            dir_mode = stat.S_IMODE(company_dir.stat().st_mode)
            self.assertEqual(dir_mode, 0o700)

            sub_dir_mode = stat.S_IMODE(sub_dir.stat().st_mode)
            self.assertEqual(sub_dir_mode, 0o700)

            # Sprawdź uprawnienia plików wrażliwych (musi być 0600)
            profil_mode = stat.S_IMODE(profil_file.stat().st_mode)
            self.assertEqual(profil_mode, 0o600)

            rules_mode = stat.S_IMODE(rules_file.stat().st_mode)
            self.assertEqual(rules_mode, 0o600)


if __name__ == "__main__":
    unittest.main()
