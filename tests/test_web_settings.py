"""
tests/test_web_settings.py
Testy integracyjne modułu Ustawień Firmy, KSeF i Silników AI (Kamień Milowy M6).
"""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import app
from src.core.company import CompanyProfile


class TestWebSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Kopia zapasowa profilu
        cls.profile = CompanyProfile.load_by_nip("7770001122")
        if not cls.profile:
            from tests.fixtures import setup_test_company
            cls.profile = setup_test_company()
        cls.initial_token = cls.profile.ksef.token
        cls.initial_env = cls.profile.ksef.srodowisko
        cls.initial_llm = dict(getattr(cls.profile, "llm", {}))
        cls.initial_stawka = cls.profile.domyslna_stawka_ryczaltu
        cls.initial_typ_zus = cls.profile.zus.typ
        cls.initial_chorobowe = cls.profile.zus.chorobowe_dobrowolne
        cls.initial_vat = cls.profile.platnik_vat
        cls.initial_zasada = cls.profile.zus.zasada_odliczen
        cls.initial_metoda_zdr = cls.profile.zus.metoda_zdrowotna
        cls.initial_prog_zdr = cls.profile.zus.prog_zdrowotnej_uproszczony
        cls.initial_historia = dict(cls.profile.zus.historia_typow)

    @classmethod
    def tearDownClass(cls):
        # Przywrócenie pierwotnego profilu
        if cls.profile and cls.initial_token:
            cls.profile.set_ksef_token(cls.initial_token, cls.initial_env)
        if cls.profile:
            cls.profile.llm = cls.initial_llm
            cls.profile.update_tax_and_zus_settings(
                domyslna_stawka_ryczaltu=cls.initial_stawka,
                typ_zus=cls.initial_typ_zus,
                chorobowe_dobrowolne=cls.initial_chorobowe,
                platnik_vat=cls.initial_vat,
                zasada_odliczen=cls.initial_zasada,
                metoda_zdrowotna=cls.initial_metoda_zdr,
                prog_zdrowotnej_uproszczony=cls.initial_prog_zdr,
            )
            cls.profile.zus.historia_typow = cls.initial_historia
            cls.profile.save()
        import os
        os.environ.pop("TAXPILOT_LLM_MODEL", None)
        os.environ.pop("TAXPILOT_LLM_PROVIDER", None)
        os.environ.pop("GEMINI_API_KEY", None)

    def setUp(self):
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP
        self.client.cookies[COOKIE_ACTIVE_NIP] = self.profile.nip

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
        reloaded = CompanyProfile.load_by_nip(self.profile.nip)
        self.assertEqual(reloaded.ksef.token, "nowy_testowy_token_ksef_12345")
        self.assertEqual(reloaded.ksef.srodowisko, "TEST")

    @patch("src.web.routers.settings.save_key_to_env")
    def test_update_llm_settings(self, mock_save_env):
        """Test aktualizacji wyboru dostawcy AI POST /ustawienia/llm."""
        response = self.client.post(
            "/ustawienia/llm",
            data={
                "provider": "gemini",
                "model": "gemini-1.5-flash",
                "api_key": "test_fake_api_key_gemini",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Konfiguracja silnika AI została zapisana", html)
        mock_save_env.assert_called()

    @patch("src.web.routers.settings.save_key_to_env")
    def test_update_llm_settings_custom_model_persists(self, mock_save_env):
        """Test czy niestandardowy model (np. gemini-3.8-flash) poprawnie zapisuje się i jest respektowany."""
        from src.web.services.llm.factory import LLMProviderFactory

        response = self.client.post(
            "/ustawienia/llm",
            data={
                "provider": "gemini",
                "model": "models/gemini-3.8-flash",
                "api_key": "test_fake_api_key_gemini",
            },
        )
        self.assertEqual(response.status_code, 200)

        # Sprawdzenie przeładowania profilu
        reloaded = CompanyProfile.load_by_nip(self.profile.nip)
        self.assertEqual(reloaded.llm.get("model"), "models/gemini-3.8-flash")
        self.assertEqual(reloaded.llm.get("provider"), "gemini")

        # Sprawdzenie czy fabryka użyje wskazanego modelu
        provider = LLMProviderFactory.get_provider(profile=reloaded)
        self.assertEqual(provider.model_name, "gemini-3.8-flash")

    @patch("src.web.routers.settings.save_key_to_env")
    def test_update_llm_settings_antigravity(self, mock_save_env):
        """Test konfiguracji providera Antigravity (agy)."""
        from src.web.services.llm.factory import LLMProviderFactory
        from src.web.services.llm.antigravity_provider import AntigravityProvider

        response = self.client.post(
            "/ustawienia/llm",
            data={
                "provider": "antigravity",
                "model": "antigravity-cli",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Konfiguracja silnika AI została zapisana", html)
        self.assertIn("Antigravity", html)

        reloaded = CompanyProfile.load_by_nip(self.profile.nip)
        self.assertEqual(reloaded.llm.get("provider"), "antigravity")

        provider = LLMProviderFactory.get_provider(profile=reloaded)
        self.assertIsInstance(provider, AntigravityProvider)
        self.assertEqual(provider.provider_name, "antigravity")

    def test_update_tax_and_zus_settings(self):
        """Test aktualizacji parametrów podatkowo-składkowych POST /ustawienia/podatki."""
        from src.core.company import TypZUS

        response = self.client.post(
            "/ustawienia/podatki",
            data={
                "stawka_ryczaltu": "0.085",
                "typ_zus": "MALY_ZUS_PLUS",
                "chorobowe_dobrowolne": "true",
                "platnik_vat": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Parametry podatkowo-składkowe zostały pomyślnie zaktualizowane", html)
        self.assertIn("8.5%", html)
        self.assertIn("MALY_ZUS_PLUS", html)

        # Sprawdzenie trwałości na dysku w profil.json
        reloaded = CompanyProfile.load_by_nip(self.profile.nip)
        self.assertAlmostEqual(reloaded.domyslna_stawka_ryczaltu, 0.085)
        self.assertEqual(reloaded.zus.typ, TypZUS.MALY_ZUS_PLUS)
        self.assertTrue(reloaded.zus.chorobowe_dobrowolne)
        self.assertTrue(reloaded.platnik_vat)

        # Test wyłączenia chorobowego i zwolnienia z VAT (puste checkboxy)
        response2 = self.client.post(
            "/ustawienia/podatki",
            data={
                "stawka_ryczaltu": "0.14",
                "typ_zus": "ULGA_NA_START",
            },
        )
        self.assertEqual(response2.status_code, 200)
        reloaded2 = CompanyProfile.load_by_nip(self.profile.nip)
        self.assertAlmostEqual(reloaded2.domyslna_stawka_ryczaltu, 0.14)
        self.assertEqual(reloaded2.zus.typ, TypZUS.ULGA_NA_START)
        self.assertFalse(reloaded2.zus.chorobowe_dobrowolne)
        self.assertFalse(reloaded2.platnik_vat)


if __name__ == "__main__":
    unittest.main()
