import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from src.core.company import CompanyProfile, FormaOpodatkowania, KSeFConfig, TypZUS, ZUSConfig
from src.core.security import (
    _ENCRYPTED_PREFIX,
    decrypt_secret,
    derive_fernet_key,
    encrypt_secret,
)


class TestSecretEncryption(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="taxpilot_test_sec_"))
        self.original_enc_key = os.environ.get("TAXPILOT_ENCRYPTION_KEY")
        if "TAXPILOT_ENCRYPTION_KEY" in os.environ:
            del os.environ["TAXPILOT_ENCRYPTION_KEY"]

    def tearDown(self):
        if self.original_enc_key is not None:
            os.environ["TAXPILOT_ENCRYPTION_KEY"] = self.original_enc_key
        elif "TAXPILOT_ENCRYPTION_KEY" in os.environ:
            del os.environ["TAXPILOT_ENCRYPTION_KEY"]

        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_derive_fernet_key_deterministic(self):
        passphrase = "my-secure-taxpilot-passphrase-2026"
        key1 = derive_fernet_key(passphrase)
        key2 = derive_fernet_key(passphrase)
        self.assertEqual(key1, key2)
        # Should be a valid 44-byte urlsafe base64 key for Fernet
        f = Fernet(key1)
        self.assertIsNotNone(f)

    def test_encrypt_and_decrypt_with_passphrase(self):
        passphrase = "passphrase-for-testing"
        secret = "ksef_test_token_1234567890abcdef"

        ciphertext = encrypt_secret(secret, key=passphrase)
        self.assertIsNotNone(ciphertext)
        assert ciphertext is not None
        self.assertTrue(ciphertext.startswith(_ENCRYPTED_PREFIX))
        self.assertNotEqual(ciphertext, secret)

        decrypted = decrypt_secret(ciphertext, key=passphrase)
        self.assertEqual(decrypted, secret)

    def test_encrypt_and_decrypt_with_fernet_key(self):
        raw_key = Fernet.generate_key().decode("utf-8")
        secret = "secret_api_key_xyz_789"

        ciphertext = encrypt_secret(secret, key=raw_key)
        self.assertIsNotNone(ciphertext)
        assert ciphertext is not None
        self.assertTrue(ciphertext.startswith(_ENCRYPTED_PREFIX))

        decrypted = decrypt_secret(ciphertext, key=raw_key)
        self.assertEqual(decrypted, secret)

    def test_encrypt_without_key_returns_plaintext(self):
        secret = "plain_token_without_encryption"
        # No key in env and no key argument
        result = encrypt_secret(secret)
        self.assertEqual(result, secret)

    def test_decrypt_unencrypted_returns_plaintext(self):
        secret = "plain_token_already"
        result = decrypt_secret(secret, key="some-key")
        self.assertEqual(result, secret)

    def test_decrypt_encrypted_without_key_raises_error(self):
        ciphertext = encrypt_secret("my_token", key="temp-key")
        # Trying to decrypt without a key set
        with self.assertRaises(ValueError) as ctx:
            decrypt_secret(ciphertext)
        self.assertIn("TAXPILOT_ENCRYPTION_KEY", str(ctx.exception))

    def test_decrypt_encrypted_with_wrong_key_raises_error(self):
        ciphertext = encrypt_secret("my_token", key="correct-key")
        with self.assertRaises(ValueError) as ctx:
            decrypt_secret(ciphertext, key="wrong-key")
        self.assertIn("nieprawidłowy klucz", str(ctx.exception))

    def test_company_profile_save_and_load_with_encryption(self):
        os.environ["TAXPILOT_ENCRYPTION_KEY"] = "company-secret-key-32chars-long!"
        company_dir = self.test_dir / "1234567890-TestCompany"

        profile = CompanyProfile(
            nip="1234567890",
            nazwa="TestCompany",
            forma_opodatkowania=FormaOpodatkowania.RYCZALT,
            domyslna_stawka_ryczaltu=0.12,
            platnik_vat=True,
            zus=ZUSConfig(typ=TypZUS.PELNY_ZUS),
            ksef=KSeFConfig(srodowisko="TEST", token="super-secret-ksef-token-123"),
            llm={"provider": "openai", "api_key": "sk-secret-llm-key"},
            _custom_path=company_dir,
        )

        # 1. Save profile to disk
        profile_path = profile.save()
        self.assertTrue(profile_path.exists())

        # 2. Inspect raw file on disk – secrets must be encrypted
        with open(profile_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        saved_token = raw_data["ksef"]["token"]
        saved_llm_key = raw_data["llm"]["api_key"]

        self.assertTrue(saved_token.startswith(_ENCRYPTED_PREFIX))
        self.assertTrue(saved_llm_key.startswith(_ENCRYPTED_PREFIX))
        self.assertNotIn("super-secret-ksef-token-123", json.dumps(raw_data))
        self.assertNotIn("sk-secret-llm-key", json.dumps(raw_data))

        # 3. Load profile from directory – secrets must be transparently decrypted in memory
        loaded_profile = CompanyProfile.load_from_dir(company_dir)
        self.assertEqual(loaded_profile.ksef.token, "super-secret-ksef-token-123")
        self.assertEqual(loaded_profile.llm.get("api_key"), "sk-secret-llm-key")

    def test_company_profile_save_and_load_without_encryption_backward_compat(self):
        company_dir = self.test_dir / "9999999999-PlainCompany"

        profile = CompanyProfile(
            nip="9999999999",
            nazwa="PlainCompany",
            forma_opodatkowania=FormaOpodatkowania.RYCZALT,
            domyslna_stawka_ryczaltu=0.12,
            platnik_vat=True,
            zus=ZUSConfig(typ=TypZUS.PELNY_ZUS),
            ksef=KSeFConfig(srodowisko="TEST", token="plain-ksef-token-xyz"),
            _custom_path=company_dir,
        )

        profile.save()

        # Load back
        loaded = CompanyProfile.load_from_dir(company_dir)
        self.assertEqual(loaded.ksef.token, "plain-ksef-token-xyz")


if __name__ == "__main__":
    unittest.main()
