"""
src/core/security.py
Moduł kryptograficzny dla TaxPilot AI (SEC-13).
Zapewnia opcjonalne szyfrowanie symetryczne danych wrażliwych at-rest (tokeny KSeF, klucze API LLM)
za pomocą algorytmu Fernet (AES-128-CBC + HMAC-SHA256) z biblioteki cryptography.
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Stała sól aplikacyjna dla wyprowadzania klucza z hasła
_APP_SALT = b"TaxPilotAI_Secret_Salt_v1_2026"
_ENCRYPTED_PREFIX = "enc:fernet:"


def derive_fernet_key(passphrase: str) -> bytes:
    """Wyprowadza klucz Fernet z dowolnego hasła tekstowego za pomocą PBKDF2HMAC (SHA-256)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_APP_SALT,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def get_fernet_instance(key_or_passphrase: Optional[str] = None) -> Optional[Fernet]:
    """Zwraca instancję Fernet dla podanego klucza lub zmiennej TAXPILOT_ENCRYPTION_KEY."""
    raw_key = key_or_passphrase or os.getenv("TAXPILOT_ENCRYPTION_KEY", "").strip()
    if not raw_key:
        return None

    try:
        # Jeśli klucz jest już prawidłowym 32-bajtowym kluczem Fernet w base64
        if len(raw_key) == 44 and raw_key.endswith("="):
            return Fernet(raw_key.encode("utf-8"))
    except Exception:
        pass

    # W przeciwnym razie wyprowadź klucz z hasła za pomocą PBKDF2
    derived = derive_fernet_key(raw_key)
    return Fernet(derived)


def encrypt_secret(plaintext: Optional[str], key: Optional[str] = None) -> Optional[str]:
    """
    Szyfruje wartość tekstową (np. token KSeF, klucz API) przy użyciu Fernet (SEC-13).
    Jeśli klucz szyfrowania nie jest skonfigurowany, zwraca wartość niezmienioną.
    Jeśli wartość jest już zaszyfrowana (zaczyna się od 'enc:fernet:'), zwraca ją bez zmian.
    """
    if not plaintext or not plaintext.strip():
        return plaintext

    clean = plaintext.strip()
    if clean.startswith(_ENCRYPTED_PREFIX):
        return clean

    fernet = get_fernet_instance(key)
    if not fernet:
        return clean

    encrypted_bytes = fernet.encrypt(clean.encode("utf-8"))
    return f"{_ENCRYPTED_PREFIX}{encrypted_bytes.decode('utf-8')}"


def decrypt_secret(ciphertext: Optional[str], key: Optional[str] = None) -> Optional[str]:
    """
    Deszyfruje wartość tekstową zaszyfrowaną prefiksem 'enc:fernet:'.
    Jeśli wartość nie jest zaszyfrowana, zwraca ją bez zmian.
    Jeśli wartość jest zaszyfrowana, a brak klucza lub klucz jest błędny, zgłasza ValueError.
    """
    if not ciphertext or not ciphertext.strip():
        return ciphertext

    clean = ciphertext.strip()
    if not clean.startswith(_ENCRYPTED_PREFIX):
        return clean

    fernet = get_fernet_instance(key)
    if not fernet:
        raise ValueError(
            "Wykryto zaszyfrowany sekret w profilu, lecz brak klucza szyfrowania. "
            "Ustaw zmienną środowiskową TAXPILOT_ENCRYPTION_KEY."
        )

    raw_token = clean[len(_ENCRYPTED_PREFIX) :].encode("utf-8")
    try:
        decrypted_bytes = fernet.decrypt(raw_token)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise ValueError(
            "Nie udało się odszyfrować sekretu. Podano nieprawidłowy klucz TAXPILOT_ENCRYPTION_KEY."
        ) from exc
