"""
tests/test_web_settings.py
Testy integracyjne modułu Ustawień Firmy, KSeF i Silników AI (Kamień Milowy M6).
"""
import unittest
from fastapi.testclient import TestClient

from src.web.app import app
from src.core.company import CompanyProfile


class TestWebSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Kopia zapasowa profilu
        cls.profile = CompanyProfile.load_by_nip("5322030067")
        cls.initial_token = cls.profile.ksef.token
        cls.initial_env = cls.profile.ksef.srodowisko

    @classmethod
    def tearDownClass(cls):
        # Przywrócenie pierwotnego profilu
        if cls.profile and cls.initial_token:
            cls.profile.set_ksef_token(cls.initial_token, cls.initial_env)

    def setUp(self):
        self.client = TestClient(app)

    def test_settings_view_renders(self):
        """Test renderowania strony ustawień GET /ustawienia."""
        response = self.client.get("/ustawienia")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("Ustawienia Firmy & Integracje", html)
        self.assertIn("Profil Podatnika (JDG)", html)
        self.assertIn("Bramka Krajowego Systemu e-Faktur", html)
        self.assertIn("Silnik Sztucznej Inteligencji", html)
        self.assertIn("Wdrożenie Hostingowe & Konteneryzacja", html)

    def test_update_ksef_settings(self):
        """Test aktualizacji tokenu i środowiska KSeF POST /ustawienia/ksef."""
        response = self.client.post(
            "/ustawienia/ksef",
            data={
                "token": "nowy_testowy_token_ksef_12345",
                "srodowisko": "TEST",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Konfiguracja KSeF została pomyślnie zaktualizowana", html)

        # Sprawdzenie czy profil został zaktualizowany
        reloaded = CompanyProfile.load_by_nip("5322030067")
        self.assertEqual(reloaded.ksef.token, "nowy_testowy_token_ksef_12345")
        self.assertEqual(reloaded.ksef.srodowisko, "TEST")

    def test_update_llm_settings(self):
        """Test aktualizacji wyboru dostawcy AI POST /ustawienia/llm."""
        response = self.client.post(
            "/ustawienia/llm",
            data={
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key": "test_fake_api_key_gemini",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Konfiguracja silnika AI została zapisana", html)


if __name__ == "__main__":
    unittest.main()
