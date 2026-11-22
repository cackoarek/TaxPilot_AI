"""
tests/test_audit03_hardening.py
Testy weryfikujące twardnienia bezpieczeństwa i odporności po sesji AUDIT-03:
- SEC-16: Open Redirect w /firmy/switch i /firmy/period
- SEC-17: atomic_write_bytes z uprawnieniami 0600
- SEC-18: save_key_to_env z sanityzacją CRLF i uprawnieniami 0600
- SEC-19: html.escape w dymkach czatu Copilota
- TAX-1: Ochrona nadwyżki VAT przed ujemnymi wartościami
"""

import os
import stat
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.io import atomic_write_bytes
from src.skills.vat_tools import RejestrVATMiesiaca, calculate_vat_settlement
from src.web.app import app
from src.web.routers.copilot import render_user_bubble
from src.web.routers.settings import save_key_to_env


class TestAudit03Hardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_env = os.environ.get("TAXPILOT_DATA_DIR")
        os.environ["TAXPILOT_DATA_DIR"] = self.tmp_dir.name

    def tearDown(self):
        self.tmp_dir.cleanup()
        if self.orig_env is not None:
            os.environ["TAXPILOT_DATA_DIR"] = self.orig_env
        else:
            os.environ.pop("TAXPILOT_DATA_DIR", None)

    def test_sec16_open_redirect_switch_company(self):
        # Próba open redirect na zewnętrzną domenę
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "https://evil.com/phish"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        # Powinno bezpiecznie przekierować na "/"
        self.assertEqual(response.headers["location"], "/")

        # Próba protocol-relative URL (//evil.com)
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "//evil.com"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

        # Prawidłowy bezpieczny URL lokalny (/przeglad)
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/przeglad"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/przeglad")

    def test_sec16_open_redirect_switch_period(self):
        # Próba open redirect w switch_period
        response = self.client.post(
            "/firmy/period",
            data={"rok": "2026", "miesiac": "10", "redirect_url": "https://attacker.org"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

        # Prawidłowa ścieżka lokalna
        response = self.client.post(
            "/firmy/period",
            data={"rok": "2026", "miesiac": "10", "redirect_url": "/faktury"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/faktury")

    def test_sec17_atomic_write_bytes(self):
        target = Path(self.tmp_dir.name) / "test_file.bin"
        data = b"TaxPilot Binary Secret Payload"
        written = atomic_write_bytes(target, data, mode=0o600)
        self.assertTrue(written.exists())
        self.assertEqual(written.read_bytes(), data)

        # Sprawdzenie uprawnień na systemach POSIX
        if os.name == "posix":
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_sec18_save_key_to_env_crlf_protection(self):
        orig_cwd = os.getcwd()
        try:
            os.chdir(self.tmp_dir.name)
            # Próba wstrzyknięcia CRLF w kluczu i wartości
            save_key_to_env("EVIL_KEY\nINJECTED_VAR=1", "val1\r\nANOTHER_INJECTED=2")

            env_content = Path(".env").read_text(encoding="utf-8")
            self.assertNotIn("INJECTED_VAR=1", env_content)
            self.assertNotIn("ANOTHER_INJECTED=2", env_content)
            self.assertIn("EVIL_KEY=", env_content)

            # Sprawdzenie uprawnień .env
            if os.name == "posix":
                mode = stat.S_IMODE(Path(".env").stat().st_mode)
                self.assertEqual(mode, 0o600)
        finally:
            os.chdir(orig_cwd)

    def test_sec19_copilot_html_escape(self):
        dangerous_input = 'Alert <script>alert("xss")</script> & "quotes" \'apostrophe\''
        bubble_html = render_user_bubble(dangerous_input)
        self.assertNotIn("<script>", bubble_html)
        self.assertIn("&lt;script&gt;", bubble_html)
        self.assertIn("&quot;quotes&quot;", bubble_html)
        self.assertIn("&#x27;apostrophe&#x27;", bubble_html)

    def test_tax1_vat_settlement_negative_surplus_clamped(self):
        rejestr = RejestrVATMiesiaca(rok="2026", miesiac="10")
        rejestr.suma_sprzedaz_vat_nalezy = Decimal("1000.00")
        rejestr.suma_zakupy_vat_naliczony_odliczenie = Decimal("200.00")

        # Ujemna nadwyżka powinna zostać zignorowana (clamped do 0.00)
        result = calculate_vat_settlement(rejestr, nadwyzka_z_poprzedniego_miesiaca=Decimal("-500.00"))
        self.assertEqual(result.nadwyzka_z_poprzedniego_miesiaca, Decimal("0.00"))
        self.assertEqual(result.vat_naliczony, Decimal("200.00"))
        self.assertEqual(result.vat_do_zaplaty_zaokraglony, 800)


if __name__ == "__main__":
    unittest.main()
