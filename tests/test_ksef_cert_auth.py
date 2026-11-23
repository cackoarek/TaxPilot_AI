"""
tests/test_ksef_cert_auth.py
Kompleksowe testy uwierzytelniania w KSeF 2.0 za pomocą certyfikatów (.crt + .key / XAdES-BES)
oraz integracji z profilem firmy i interfejsem Web UI.
"""

import base64
import datetime
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from lxml import etree

from src.core.company import CompanyProfile, FormaOpodatkowania
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_1_ingestion.xades_signer import (
    parse_certificate_info,
    sign_ksef_auth_token_request,
    validate_key_pair,
)
from src.web.app import app


def generate_test_cert_and_key(key_type: str = "rsa", password: Optional[bytes] = None):
    """Generuje parę klucz prywatny + certyfikat X.509 do celów testowych."""
    key: Any
    if key_type == "rsa":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Firma Testowa Sp. z o.o."),
            x509.NameAttribute(NameOID.COMMON_NAME, "Jan Kowalski (NIP 7770001122)"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(123456789012345)
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    enc: serialization.KeySerializationEncryption
    if password:
        enc = serialization.BestAvailableEncryption(password)
    else:
        enc = serialization.NoEncryption()

    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        enc,
    )
    return cert_pem, key_pem, key, cert


class TestKSeFCertificateAuth(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.profile = CompanyProfile(
            nip="7770001122",
            nazwa="Firma Testowa Sp. z o.o.",
            forma_opodatkowania=FormaOpodatkowania.RYCZALT,
            katalog_nazwa="7770001122-Firma_Testowa",
            _custom_path=self.temp_dir,
        )
        self.cert_pem, self.key_pem, self.key_obj, self.cert_obj = generate_test_cert_and_key("rsa")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_xades_signer_and_verification(self):
        """Weryfikuje poprawne wygenerowanie i podpisanie dokumentu AuthTokenRequest."""
        challenge = "20261123-CR-TEST-998877"
        nip = "7770001122"

        signed_xml = sign_ksef_auth_token_request(
            challenge=challenge,
            nip=nip,
            cert_bytes=self.cert_pem,
            key_bytes=self.key_pem,
        )

        self.assertIsInstance(signed_xml, bytes)
        self.assertIn(b"AuthTokenRequest", signed_xml)
        self.assertIn(b"http://ksef.mf.gov.pl/auth/token/2.0", signed_xml)
        self.assertIn(b"Signature", signed_xml)
        self.assertIn(b"QualifyingProperties", signed_xml)
        self.assertIn(b"SignedProperties", signed_xml)
        self.assertIn(challenge.encode("utf-8"), signed_xml)

        # Weryfikacja kryptograficzna podpisu
        root = etree.fromstring(signed_xml)
        sig = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
        self.assertIsNotNone(sig)
        s_info = sig.find("{http://www.w3.org/2000/09/xmldsig#}SignedInfo")
        self.assertIsNotNone(s_info)
        s_val = sig.find("{http://www.w3.org/2000/09/xmldsig#}SignatureValue").text
        s_cert_b64 = sig.find(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate").text

        cert_loaded = x509.load_der_x509_certificate(base64.b64decode(s_cert_b64))
        s_info_c14n = etree.tostring(s_info, method="c14n", exclusive=True)
        pub = cert_loaded.public_key()
        assert isinstance(pub, rsa.RSAPublicKey)
        pub.verify(
            base64.b64decode(s_val),
            s_info_c14n,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def test_parse_certificate_info(self):
        """Sprawdza wyciąganie metadanych z certyfikatu X.509."""
        info = parse_certificate_info(self.cert_pem)
        self.assertTrue(info["is_valid"])
        self.assertIn("Jan Kowalski", info["subject_cn"])
        self.assertIn("Firma Testowa", info["subject_o"])
        self.assertEqual(info["serial_number"], "123456789012345")
        self.assertIsNotNone(info["sha256_fingerprint"])

    def test_validate_key_pair(self):
        """Sprawdza dopasowanie klucza prywatnego do certyfikatu."""
        # 1. Poprawna para
        ok, msg = validate_key_pair(self.cert_pem, self.key_pem)
        self.assertTrue(ok)

        # 2. Niepasujący klucz
        _, other_key_pem, _, _ = generate_test_cert_and_key("rsa")
        ok_wrong, msg_wrong = validate_key_pair(self.cert_pem, other_key_pem)
        self.assertFalse(ok_wrong)

        # 3. Klucz zabezpieczony hasłem
        cert_p, key_p, _, _ = generate_test_cert_and_key("rsa", password=b"tajne123")
        ok_pwd, _ = validate_key_pair(cert_p, key_p, key_password=b"tajne123")
        self.assertTrue(ok_pwd)

        ok_bad_pwd, _ = validate_key_pair(cert_p, key_p, key_password=b"zle_haslo")
        self.assertFalse(ok_bad_pwd)

    def test_company_profile_certificate_storage(self):
        """Sprawdza zapisywanie i odczyt certyfikatów w profilu firmy."""
        self.assertFalse(self.profile.has_ksef_certificate())
        self.assertFalse(self.profile.has_ksef_offline_certificate())

        off_cert, off_key, _, _ = generate_test_cert_and_key("rsa")

        self.profile.set_ksef_certificates(
            auth_cert_bytes=self.cert_pem,
            auth_key_bytes=self.key_pem,
            auth_password="haslo_auth",
            offline_cert_bytes=off_cert,
            offline_key_bytes=off_key,
            offline_password="haslo_off",
            auth_type="certyfikat",
            srodowisko="TEST",
        )

        self.assertTrue(self.profile.has_ksef_certificate())
        self.assertTrue(self.profile.has_ksef_offline_certificate())
        self.assertEqual(self.profile.ksef.auth_type, "certyfikat")
        self.assertEqual(self.profile.ksef.srodowisko, "TEST")

        # Sprawdzenie istnienia plików na dysku
        auth_cert_p = self.profile.get_auth_cert_path()
        auth_key_p = self.profile.get_auth_key_path()
        self.assertIsNotNone(auth_cert_p)
        self.assertIsNotNone(auth_key_p)
        assert auth_cert_p is not None and auth_key_p is not None
        self.assertTrue(auth_cert_p.exists())
        self.assertTrue(auth_key_p.exists())

        # Sprawdzenie przeładowania z dysku
        loaded_profile = CompanyProfile.load_from_dir(self.temp_dir)
        self.assertEqual(loaded_profile.ksef.auth_type, "certyfikat")
        self.assertEqual(loaded_profile.ksef.key_password, "haslo_auth")
        self.assertEqual(loaded_profile.ksef.offline_key_password, "haslo_off")
        self.assertTrue(loaded_profile.has_ksef_certificate())

    def test_ksef_client_certificate_authentication_flow(self):
        """Testuje pełny proces uwierzytelnienia w KSeFClient z mockami API Ministerstwa Finansów."""
        self.profile.set_ksef_certificates(
            auth_cert_bytes=self.cert_pem,
            auth_key_bytes=self.key_pem,
            auth_type="certyfikat",
            srodowisko="TEST",
        )

        client = KSeFClient(self.profile)
        self.assertTrue(client.is_certificate_configured())
        self.assertTrue(client.is_auth_configured())

        with patch.object(client.session, "post") as mock_post, patch.object(client.session, "get") as mock_get:
            # 1. /auth/challenge
            mock_chal_resp = MagicMock()
            mock_chal_resp.status_code = 200
            mock_chal_resp.json.return_value = {"challenge": "20261123-CHALLENGE-TEST", "timestampMs": 1700000000}

            # 2. /auth/xades-signature
            mock_xades_resp = MagicMock()
            mock_xades_resp.status_code = 200
            mock_xades_resp.json.return_value = {
                "referenceNumber": "REF-12345-TEST",
                "authenticationToken": {"token": "TEMP-JWT-TOKEN"},
            }

            # 3. /auth/token/redeem
            mock_redeem_resp = MagicMock()
            mock_redeem_resp.status_code = 200
            mock_redeem_resp.json.return_value = {
                "accessToken": {"token": "FINAL-ACCESS-TOKEN-XYZ", "validUntil": "2026-11-24T12:00:00Z"},
            }

            mock_post.side_effect = [mock_chal_resp, mock_xades_resp, mock_redeem_resp]

            # 4. /auth/{ref} (polling)
            mock_stat_resp = MagicMock()
            mock_stat_resp.status_code = 200
            mock_stat_resp.json.return_value = {"status": {"code": 200, "description": "OK"}}
            mock_get.return_value = mock_stat_resp

            # Uwierzytelnienie
            token = client.authenticate()
            self.assertEqual(token, "FINAL-ACCESS-TOKEN-XYZ")
            self.assertEqual(client.access_token, "FINAL-ACCESS-TOKEN-XYZ")
            self.assertEqual(client.access_token_valid_until, "2026-11-24T12:00:00Z")

            # Weryfikacja parametrów wywołań
            self.assertEqual(mock_post.call_count, 3)
            # Drugie wywołanie to /auth/xades-signature
            xades_call_args = mock_post.call_args_list[1]
            self.assertIn("/auth/xades-signature", xades_call_args[0][0])
            self.assertEqual(xades_call_args[1]["headers"]["Content-Type"], "application/xml")
            self.assertIn(b"AuthTokenRequest", xades_call_args[1]["data"])

    def test_web_settings_upload_and_test_connection(self):
        """Testuje endpointy wgrywania certyfikatów i testowania połączenia w FastAPI."""
        test_client = TestClient(app)

        with patch("src.web.dependencies.get_active_profile", return_value=self.profile):
            # 1. Wgranie certyfikatów przez formularz
            auth_crt_file = io.BytesIO(self.cert_pem)
            auth_key_file = io.BytesIO(self.key_pem)

            resp_upload = test_client.post(
                "/ustawienia/ksef/certyfikaty",
                files={
                    "auth_crt": ("auth.crt", auth_crt_file, "application/x-x509-ca-cert"),
                    "auth_key": ("auth.key", auth_key_file, "application/pkcs8"),
                },
                data={
                    "switch_to_cert": "true",
                    "srodowisko": "TEST",
                },
            )

            self.assertEqual(resp_upload.status_code, 200)
            self.assertIn("Certyfikaty KSeF zostały pomyślnie wgrane", resp_upload.text)
            self.assertTrue(self.profile.has_ksef_certificate())
            self.assertEqual(self.profile.ksef.auth_type, "certyfikat")

            # 2. Test połączenia
            with patch.object(KSeFClient, "authenticate", return_value="MOCK-ACCESS-TOKEN"):
                resp_test = test_client.post("/ustawienia/ksef/test")
                self.assertEqual(resp_test.status_code, 200)
                self.assertIn("Połączenie z KSeF 2.0 nawiązane pomyślnie", resp_test.text)
                self.assertIn("Certyfikat (XAdES-BES)", resp_test.text)


if __name__ == "__main__":
    unittest.main()
