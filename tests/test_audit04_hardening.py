"""
tests/test_audit04_hardening.py
Testy weryfikujące twardnienia bezpieczeństwa i mechanizmy operacyjne po sesji AUDIT-04:
- SEC-20: Twardnienie CSRF (Double-Submit Cookie, X-Forwarded-Host, ochrona przed downgrade HTTP)
- SEC-21: Maskowanie wrażliwych danych w logach (SecretMaskingFilter)
- CONCUR-3: Blokady plikowe przy mutacjach reguł kosztowych
- OPS-1: Moduł tworzenia i bezpiecznego przywracania kopii zapasowych (z ochroną przed TarSlip CWE-22)
"""

import io
import json
import logging
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from src.core.backup import (
    calculate_file_sha256,
    create_company_backup,
    restore_company_backup,
    verify_backup_integrity,
)
from src.core.company import CompanyProfile
from src.logging_config import SecretMaskingFilter
from src.skills.cost_classifier import KwalifikacjaKosztu, ReczneKwalifikacjeService
from src.web.app import app
from src.web.config import COOKIE_CSRF_TOKEN
from src.web.utils.security import (
    generate_csrf_token,
    is_trusted_origin,
    validate_csrf_token,
)


class TestAudit04Hardening(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        self.orig_env = os.environ.get("TAXPILOT_DATA_DIR")
        os.environ["TAXPILOT_DATA_DIR"] = str(self.tmp_path)
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp_dir.cleanup()
        if self.orig_env is not None:
            os.environ["TAXPILOT_DATA_DIR"] = self.orig_env
        else:
            os.environ.pop("TAXPILOT_DATA_DIR", None)

    # -------------------------------------------------------------------------
    # SEC-20: CSRF Hardening Tests
    # -------------------------------------------------------------------------

    def test_sec20_generate_and_validate_csrf_token(self):
        token1 = generate_csrf_token()
        token2 = generate_csrf_token()
        self.assertGreaterEqual(len(token1), 32)
        self.assertNotEqual(token1, token2)

        # Dopasowane tokeny
        req1 = Request({"type": "http", "headers": [(b"cookie", f"{COOKIE_CSRF_TOKEN}={token1}".encode())]})
        self.assertTrue(validate_csrf_token(req1, token1))

        # Niedopasowane tokeny
        self.assertFalse(validate_csrf_token(req1, token2))
        self.assertFalse(validate_csrf_token(req1, None))
        self.assertFalse(validate_csrf_token(req1, ""))

        # Brak ciasteczka w żądaniu
        req_no_cookie = Request({"type": "http", "headers": []})
        self.assertFalse(validate_csrf_token(req_no_cookie, token1))

    def test_sec20_is_trusted_origin_proxy_and_scheme(self):
        # 1. Zwykły request lokalny z pasującym Host
        req = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/firmy/switch",
                "headers": [
                    (b"host", b"localhost:8000"),
                    (b"origin", b"http://localhost:8000"),
                ],
                "scheme": "http",
            }
        )
        self.assertTrue(is_trusted_origin(req))

        # 2. Reverse proxy: Host to kontener, ale X-Forwarded-Host i X-Forwarded-Proto pasują do Origin
        req_proxy = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/firmy/switch",
                "headers": [
                    (b"host", b"127.0.0.1:8000"),
                    (b"x-forwarded-host", b"taxpilot.mojadomena.pl"),
                    (b"x-forwarded-proto", b"https"),
                    (b"origin", b"https://taxpilot.mojadomena.pl"),
                ],
                "scheme": "http",
            }
        )
        self.assertTrue(is_trusted_origin(req_proxy))

        # 3. Ochrona przed protocol downgrade: żądanie po HTTPS, ale origin podany jako HTTP
        req_downgrade = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/firmy/switch",
                "headers": [
                    (b"host", b"taxpilot.mojadomena.pl"),
                    (b"origin", b"http://taxpilot.mojadomena.pl"),
                ],
                "scheme": "https",
            }
        )
        self.assertFalse(is_trusted_origin(req_downgrade))

        # 4. Całkowicie obcy Origin
        req_attacker = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/firmy/switch",
                "headers": [
                    (b"host", b"localhost:8000"),
                    (b"origin", b"https://malicious-site.com"),
                ],
                "scheme": "http",
            }
        )
        self.assertFalse(is_trusted_origin(req_attacker))

    def test_sec20_csrf_double_submit_middleware(self):
        # GET powinien ustawiać ciasteczko taxpilot_csrf_token
        res_get = self.client.get("/")
        self.assertEqual(res_get.status_code, 200)
        self.assertIn(COOKIE_CSRF_TOKEN, res_get.cookies)
        csrf_token = res_get.cookies[COOKIE_CSRF_TOKEN]

        # POST z poprawnym nagłówkiem X-CSRF-Token i tym samym ciasteczkiem
        res_valid = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            cookies={COOKIE_CSRF_TOKEN: csrf_token},
            headers={"X-CSRF-Token": csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(res_valid.status_code, 303)

        # POST z błędnym nagłówkiem X-CSRF-Token
        res_invalid = self.client.post(
            "/firmy/switch",
            data={"nip": "7770001122", "redirect_url": "/"},
            cookies={COOKIE_CSRF_TOKEN: csrf_token},
            headers={"X-CSRF-Token": "invalid_csrf_token_12345"},
            follow_redirects=False,
        )
        self.assertEqual(res_invalid.status_code, 403)
        self.assertIn("Nieprawidłowy token CSRF", res_invalid.text)

    # -------------------------------------------------------------------------
    # SEC-21: Secret Masking in Logging Tests
    # -------------------------------------------------------------------------

    def test_sec21_secret_masking_filter(self):
        masker = SecretMaskingFilter()

        # Test Gemini Key
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Init with Gemini key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7",
            args=(),
            exc_info=None,
        )
        masker.filter(record)
        self.assertNotIn("AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7", record.msg)
        self.assertIn("AIza...[MASKED]", record.msg)

        # Test OpenAI Key
        record_openai = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="OpenAI request failed with sk-proj1234567890abcdef1234567890abcdef",
            args=(),
            exc_info=None,
        )
        masker.filter(record_openai)
        self.assertNotIn("sk-proj1234567890abcdef1234567890abcdef", record_openai.msg)
        self.assertIn("sk-...[MASKED]", record_openai.msg)

        # Test Bearer Token
        record_bearer = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Sending header: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDc",
            args=(),
            exc_info=None,
        )
        masker.filter(record_bearer)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", record_bearer.msg)
        self.assertIn("Bearer [MASKED_TOKEN]", record_bearer.msg)

        # Test token w args
        record_args = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="Connecting with token: %s",
            args=("sk-ant-api03-abcdef1234567890abcdef1234567890",),
            exc_info=None,
        )
        masker.filter(record_args)
        formatted_args = record_args.args[0]
        self.assertNotIn("abcdef1234567890abcdef1234567890", formatted_args)
        self.assertIn("sk-ant-...[MASKED]", formatted_args)

    # -------------------------------------------------------------------------
    # CONCUR-3: Concurrency Locking on Cost Overrides
    # -------------------------------------------------------------------------

    def test_concur3_cost_overrides_locking(self):
        company_dir = self.tmp_path / "7770001122-Test_Company"
        company_dir.mkdir(parents=True, exist_ok=True)
        profil_path = company_dir / "profil.json"
        profil_path.write_text(
            json.dumps({"nip": "7770001122", "nazwa": "Test Company", "forma_opodatkowania": "RYCZALT"}),
            encoding="utf-8",
        )
        profile = CompanyProfile.load_from_dir(company_dir)

        # Zapis pojedynczej decyzji z blokadą plikową
        path1 = ReczneKwalifikacjeService.save_override(
            profile=profile,
            rok="2026",
            miesiac="10",
            numer_faktury="FV/2026/01",
            kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100,
            opis_pozycji="Kawa i herbata do biura",
        )
        self.assertTrue(path1.exists())
        overrides = ReczneKwalifikacjeService.load_overrides(profile, "2026", "10")
        self.assertIn("FV/2026/01::kawa i herbata do biura", overrides)
        self.assertEqual(overrides["FV/2026/01::kawa i herbata do biura"]["kwalifikacja"], "FIRMOWY_100")

        # Zapis hurtowy z blokadą plikową
        path2 = ReczneKwalifikacjeService.save_bulk_overrides(
            profile=profile,
            rok="2026",
            miesiac="10",
            numer_faktury="FV/2026/02",
            kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50,
            opisy_pozycji=["Paliwo PB95", "Płyn do spryskiwaczy"],
        )
        self.assertTrue(path2.exists())
        overrides_updated = ReczneKwalifikacjeService.load_overrides(profile, "2026", "10")
        self.assertIn("FV/2026/02", overrides_updated)
        self.assertIn("FV/2026/02::paliwo pb95", overrides_updated)
        self.assertIn("FV/2026/02::płyn do spryskiwaczy", overrides_updated)
        self.assertEqual(overrides_updated["FV/2026/02"]["kwalifikacja"], "SAMOCHOD_50")

    # -------------------------------------------------------------------------
    # OPS-1: Backup & Restore Engine Tests
    # -------------------------------------------------------------------------

    def test_ops1_create_verify_and_restore_backup(self):
        # 1. Tworzenie próbnej firmy
        company_dir = self.tmp_path / "1112223344-Firma_Testowa"
        company_dir.mkdir(parents=True, exist_ok=True)
        profil_path = company_dir / "profil.json"
        profil_data = {
            "nip": "1112223344",
            "nazwa": "Firma Testowa Sp. z o.o.",
            "forma_opodatkowania": "RYCZALT",
            "ksef": {"srodowisko": "TEST", "token": "dummy_token"},
        }
        with open(profil_path, "w", encoding="utf-8") as f:
            json.dump(profil_data, f)

        dummy_invoice = company_dir / "faktury" / "2026" / "10" / "sprzedaz" / "fv1.xml"
        dummy_invoice.parent.mkdir(parents=True, exist_ok=True)
        dummy_invoice.write_text("<Faktura>Test</Faktura>", encoding="utf-8")

        profile = CompanyProfile.load_from_dir(company_dir)

        # 2. Wykonanie kopii zapasowej
        backup_dir = self.tmp_path / "backups"
        archive_path, sha_path = create_company_backup(profile, output_dir=backup_dir)

        self.assertTrue(archive_path.exists())
        self.assertTrue(sha_path.exists())

        # Uprawnienia 0600
        mode = stat.S_IMODE(archive_path.stat().st_mode)
        self.assertEqual(mode, 0o600)

        # 3. Weryfikacja integralności
        is_valid, msg = verify_backup_integrity(archive_path)
        self.assertTrue(is_valid, msg)

        # 4. Próba naruszenia sumy SHA-256
        sha_path.write_text("0000000000000000000000000000000000000000000000000000000000000000  archive\n")
        is_valid_corrupt, msg_corrupt = verify_backup_integrity(archive_path)
        self.assertFalse(is_valid_corrupt)
        self.assertIn("Niezgodność sumy kontrolnej", msg_corrupt)

        # Przywrócenie poprawnego SHA
        digest = calculate_file_sha256(archive_path)
        sha_path.write_text(f"{digest}  {archive_path.name}\n")

        # 5. Przywrócenie do nowego katalogu
        restore_dir = self.tmp_path / "restored_firmy"
        restored_profile = restore_company_backup(archive_path, target_base_dir=restore_dir)

        self.assertEqual(restored_profile.nip, "1112223344")
        self.assertEqual(restored_profile.nazwa, "Firma Testowa Sp. z o.o.")
        restored_invoice = restored_profile.katalog_firmy / "faktury" / "2026" / "10" / "sprzedaz" / "fv1.xml"
        self.assertTrue(restored_invoice.exists())
        self.assertEqual(restored_invoice.read_text(encoding="utf-8"), "<Faktura>Test</Faktura>")

    def test_ops1_tarslip_prevention(self):
        # Symulacja złośliwego archiwum tar.gz z Path Traversal (CWE-22)
        malicious_tar = self.tmp_path / "evil_backup.tar.gz"

        with tarfile.open(malicious_tar, "w:gz") as tar:
            # Tworzymy element ze ścieżką ../escape.txt
            data = b"evil content"
            tarinfo = tarfile.TarInfo(name="../escape.txt")
            tarinfo.size = len(data)
            tar.addfile(tarinfo, io.BytesIO(data))

        # 1. verify_backup_integrity powinno wykryć TarSlip
        is_valid, msg = verify_backup_integrity(malicious_tar)
        self.assertFalse(is_valid)
        self.assertIn("TarSlip", msg)

        # 2. restore_company_backup powinno natychmiast rzucić ValueError
        with self.assertRaises(ValueError) as ctx:
            restore_company_backup(malicious_tar, target_base_dir=self.tmp_path / "target", verify_sha=False)
        self.assertIn("Odrzucono niebezpieczną ścieżkę", str(ctx.exception))

    def test_ops1_cli_backup_and_restore(self):
        from argparse import Namespace

        from src.cli import cmd_backup, cmd_restore

        # Tworzenie próbnej firmy
        company_dir = self.tmp_path / "1112223344-Firma_Testowa"
        company_dir.mkdir(parents=True, exist_ok=True)
        profil_path = company_dir / "profil.json"
        profil_data = {
            "nip": "1112223344",
            "nazwa": "Firma Testowa Sp. z o.o.",
            "forma_opodatkowania": "RYCZALT",
            "ksef": {"srodowisko": "TEST", "token": "dummy_token"},
        }
        with open(profil_path, "w", encoding="utf-8") as f:
            json.dump(profil_data, f)

        backup_dir = self.tmp_path / "cli_backups"
        backup_args = Namespace(nip="1112223344", output=str(backup_dir))

        # Test cmd_backup
        cmd_backup(backup_args)

        backups = list(backup_dir.glob("*.tar.gz"))
        self.assertEqual(len(backups), 1)
        archive_path = backups[0]

        # Test cmd_restore
        restore_dir = self.tmp_path / "cli_restored"
        restore_args = Namespace(archive=str(archive_path), target_dir=str(restore_dir), no_verify_sha=False)
        cmd_restore(restore_args)

        restored_profil = restore_dir / "1112223344-Firma_Testowa" / "profil.json"
        self.assertTrue(restored_profil.exists())


if __name__ == "__main__":
    unittest.main()
