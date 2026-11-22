"""
Konfiguracja globalna i ścieżki projektu TaxPilot AI.
"""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Załaduj zmienne z pliku .env, jeśli istnieje
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def get_firmy_dir() -> Path:
    """Zwraca główny katalog z danymi firm (firmy/ lub wskazany przez TAXPILOT_DATA_DIR)."""
    env_dir = os.getenv("TAXPILOT_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return BASE_DIR / "firmy"


class _FirmyDirProxy:
    """
    Dynamiczny proxy delegujący operacje do get_firmy_dir(),
    dzięki czemu zmiana TAXPILOT_DATA_DIR natychmiast przekierowuje operacje na ścieżkach.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(get_firmy_dir(), name)

    def __truediv__(self, other: Any) -> Path:
        return get_firmy_dir() / other

    def __rtruediv__(self, other: Any) -> Path:
        return Path(other) / get_firmy_dir()

    def __fspath__(self) -> str:
        return os.fspath(get_firmy_dir())

    def __str__(self) -> str:
        return str(get_firmy_dir())

    def __repr__(self) -> str:
        return repr(get_firmy_dir())

    def __eq__(self, other: Any) -> bool:
        return get_firmy_dir() == other

    def __hash__(self) -> int:
        return hash(get_firmy_dir())


FIRMY_DIR = _FirmyDirProxy()
TESTS_DIR = BASE_DIR / "tests"

# KSeF 2.0 API Base URLs
KSEF_URLS = {
    "TEST": "https://api-test.ksef.mf.gov.pl/v2",
    "PROD": "https://api.ksef.mf.gov.pl/v2",
}

DEFAULT_KSEF_ENV = os.getenv("KSEF_ENVIRONMENT", "PROD").upper()
