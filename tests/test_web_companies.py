"""
tests/test_web_companies.py
Testy jednostkowe i integracyjne dla routera firm (/firmy):
- Przełączanie firm i okresów
- Wybór 'Dodaj nową firmę do księgowania' w menu
- Widok formularza nowej firmy (/firmy/nowa)
- Endpoint autopobierania danych z rejestrów (/firmy/lookup-nip)
- Tworzenie nowej firmy, autoselekcja w ciasteczku i przekierowanie na pulpit
"""
import shutil
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import app
from src.config import FIRMY_DIR
from src.core.company import CompanyProfile
from src.web.config import COOKIE_ACTIVE_NIP


class TestWebCompanies(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_nip = "1234567890"
        self._cleanup_test_company()

    def tearDown(self):
        self._cleanup_test_company()

    def _cleanup_test_company(self):
        if FIRMY_DIR.exists():
            for p in FIRMY_DIR.glob(f"{self.test_nip}*"):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)

    def test_switch_to_new_option_redirects(self):
        """Wybór __NEW__ w menu firm natychmiast przekierowuje do /firmy/nowa."""
        response = self.client.post(
            "/firmy/switch",
            data={"nip": "__NEW__", "redirect_url": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/firmy/nowa")

    def test_new_company_page_renders(self):
        """Ekran /firmy/nowa renderuje pełny formularz dodawania firmy."""
        response = self.client.get("/firmy/nowa")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Dodaj nową firmę do księgowania", html)
        self.assertIn("Numer NIP działalności", html)
        self.assertIn("Pobierz dane z MF / CEIDG", html)
        self.assertIn("Forma Opodatkowania", html)
        self.assertIn("RYCZALT", html)
        self.assertIn("PELNY_ZUS", html)
        self.assertIn("Kody PKD", html)
        self.assertIn("KSeF 2.0", html)

    def test_navbar_includes_add_company_choice(self):
        """Pulpit zawiera opcję 'Dodaj nową firmę do księgowania' w rozwijanym menu wyboru firmy."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Dodaj nową firmę do księgowania", html)
        self.assertIn("/firmy/nowa", html)

    def test_lookup_nip_endpoint_invalid_nip(self):
        """Endpoint /firmy/lookup-nip odrzuca nieprawidłowy NIP z kodem 400."""
        response = self.client.get("/firmy/lookup-nip?nip=123")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("10-cyfrowy NIP", data["error"])

    @patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_company_info")
    def test_lookup_nip_endpoint_success(self, mock_fetch):
        """Endpoint /firmy/lookup-nip zwraca dane podmiotu pobrane z rejestru publicznego."""
        mock_fetch.return_value = {
            "nip": self.test_nip,
            "nazwa": "Alpha Test Sp. z o.o.",
            "adres": "ul. Testowa 10, 00-001 Warszawa",
            "regon": "123456789",
            "platnik_vat": True,
            "kody_pkd": ["62.01.Z", "62.02.Z"],
            "zrodlo": "Biała Lista MF",
        }
        response = self.client.get(f"/firmy/lookup-nip?nip={self.test_nip}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["nazwa"], "Alpha Test Sp. z o.o.")
        self.assertEqual(data["data"]["nip"], self.test_nip)
        self.assertTrue(data["data"]["platnik_vat"])
        self.assertIn("62.01.Z", data["data"]["kody_pkd"])

    def test_create_company_invalid_nip(self):
        """Wysłanie formularza z błędnym NIP zwraca błąd 400 i informację walidacyjną."""
        response = self.client.post(
            "/firmy/nowa",
            data={
                "nip": "123",
                "nazwa": "Błędny NIP Sp.",
                "forma_opodatkowania": "RYCZALT",
                "domyslna_stawka_ryczaltu": "0.12",
                "zus_typ": "PELNY_ZUS",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Nieprawidłowy NIP", response.text)

    @patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_company_info")
    def test_create_company_success_redirects_and_selects_tenant(self, mock_fetch):
        """Pomyślne dodanie nowej firmy tworzy strukturę, ustawia ciasteczko sesyjne i przekierowuje na pulpit."""
        mock_fetch.return_value = {
            "nip": self.test_nip,
            "nazwa": "Nowoczesne IT Jan Testowy",
            "adres": "ul. Programistów 5, 01-100 Warszawa",
            "regon": "987654321",
            "platnik_vat": True,
            "kody_pkd": ["62.01.Z"],
        }

        response = self.client.post(
            "/firmy/nowa",
            data={
                "nip": self.test_nip,
                "nazwa": "Nowoczesne IT Jan Testowy",
                "adres": "ul. Programistów 5, 01-100 Warszawa",
                "regon": "987654321",
                "forma_opodatkowania": "RYCZALT",
                "domyslna_stawka_ryczaltu": "0.12",
                "platnik_vat": "on",
                "zus_typ": "PELNY_ZUS",
                "chorobowe_dobrowolne": "on",
                "kody_pkd": "62.01.Z, 62.02.Z",
                "srodowisko_ksef": "PROD",
                "token_ksef": "TEST_TOKEN_12345",
                "auto_fetch": "false",
            },
            follow_redirects=False,
        )

        # 1. Sprawdzenie przekierowania HTTP 303 do /?nowa_firma=1
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?nowa_firma=1")

        # 2. Sprawdzenie ustawienia ciasteczka z NIP nowo dodanej firmy
        self.assertIn(COOKIE_ACTIVE_NIP, response.cookies)
        self.assertEqual(response.cookies[COOKIE_ACTIVE_NIP], self.test_nip)

        # 3. Sprawdzenie czy profil został fizycznie utworzony na dysku
        created_profile = CompanyProfile.load_by_nip(self.test_nip)
        self.assertIsNotNone(created_profile)
        self.assertEqual(created_profile.nip, self.test_nip)
        self.assertEqual(created_profile.nazwa, "Nowoczesne IT Jan Testowy")
        self.assertEqual(created_profile.domyslna_stawka_ryczaltu, 0.12)
        self.assertEqual(created_profile.ksef.token, "TEST_TOKEN_12345")
        self.assertTrue((created_profile.katalog_firmy / "profil.json").exists())
        self.assertTrue((created_profile.katalog_firmy / "reguly_kosztowe.json").exists())
        self.assertTrue((created_profile.katalog_firmy / "faktury" / "2026" / "01" / "sprzedaz" / "ksef").exists())

        # 4. Sprawdzenie czy wejście na pulpit renderuje nowo dodaną firmę i komunikat sukcesu
        resp_dashboard = self.client.get(
            "/?nowa_firma=1",
            cookies={COOKIE_ACTIVE_NIP: self.test_nip},
        )
        self.assertEqual(resp_dashboard.status_code, 200)
        self.assertIn("Nowoczesne IT Jan Testowy", resp_dashboard.text)
        self.assertIn("Nowa firma została pomyślnie dodana i aktywowana", resp_dashboard.text)


if __name__ == "__main__":
    unittest.main()
