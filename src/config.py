"""
Konfiguracja globalna i ścieżki projektu TaxPilot AI.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Załaduj zmienne z pliku .env, jeśli istnieje
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
FIRMY_DIR = BASE_DIR / "firmy"
TESTS_DIR = BASE_DIR / "tests"

# KSeF 2.0 API Base URLs
KSEF_URLS = {
    "TEST": "https://api-test.ksef.mf.gov.pl/v2",
    "PROD": "https://api.ksef.mf.gov.pl/v2",
}

DEFAULT_KSEF_ENV = os.getenv("KSEF_ENVIRONMENT", "PROD").upper()
