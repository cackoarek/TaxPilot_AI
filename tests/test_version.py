"""
tests/test_version.py
Testy jednostkowe modułu wersjonowania aplikacji (src/version.py) oraz obecności wersji w stopce UI.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.version import (
    get_version,
    get_display_version,
    clear_version_cache,
    DEFAULT_VERSION,
)
from src.web.app import app


class TestVersion(unittest.TestCase):
    def setUp(self):
        clear_version_cache()

    def tearDown(self):
        clear_version_cache()

    def test_get_version_env_var_app_version(self):
        """Zmienna APP_VERSION ma najwyższy priorytet."""
        with patch.dict(os.environ, {"APP_VERSION": "v2.5.0"}):
            clear_version_cache()
            self.assertEqual(get_version(), "v2.5.0")
            self.assertEqual(get_display_version(), "v2.5.0")

    def test_get_version_env_var_taxpilot_version(self):
        """Zmienna TAXPILOT_VERSION jest alternatywną zmienną środowiskową."""
        with patch.dict(os.environ, {"APP_VERSION": "", "TAXPILOT_VERSION": "1.8.4"}, clear=False):
            clear_version_cache()
            self.assertEqual(get_version(), "1.8.4")
            self.assertEqual(get_display_version(), "v1.8.4")

    def test_get_version_from_version_file(self):
        """Odczyt wersji ze statycznego pliku VERSION (utrzymywanego przez GitHub Actions)."""
        with patch.dict(os.environ, {"APP_VERSION": "", "TAXPILOT_VERSION": ""}, clear=False):
            with patch.object(Path, "read_text", return_value="0.3.5"):
                with patch.object(Path, "exists", return_value=True):
                    clear_version_cache()
                    self.assertEqual(get_version(), "0.3.5")
                    self.assertEqual(get_display_version(), "v0.3.5")

    def test_get_display_version_adds_v_prefix_if_missing(self):
        """Upewnia się, że get_display_version() dodaje przedrostek 'v' tylko gdy go brakuje."""
        with patch.dict(os.environ, {"APP_VERSION": "3.0.1"}):
            clear_version_cache()
            self.assertEqual(get_display_version(), "v3.0.1")

        with patch.dict(os.environ, {"APP_VERSION": "v3.0.1"}):
            clear_version_cache()
            self.assertEqual(get_display_version(), "v3.0.1")

    def test_footer_renders_version_in_web_ui(self):
        """Test czy stopka strony renderuje poprawny badge z wersją aplikacji."""
        with patch.dict(os.environ, {"APP_VERSION": "v9.9.9"}):
            clear_version_cache()
            client = TestClient(app)
            response = client.get("/")
            self.assertEqual(response.status_code, 200)
            html = response.text

            # Sprawdzenie obecności wersji w stopce
            self.assertIn("v9.9.9", html)
            self.assertIn("Wersja aplikacji", html)
            self.assertIn("<footer", html)


if __name__ == "__main__":
    unittest.main()
