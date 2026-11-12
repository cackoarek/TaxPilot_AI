"""
tests/test_web_settlement.py
Testy integracyjne modułu Wstępnego Przeglądu i Akceptacji Dokumentów (Pre-settlement Review - Kamień Milowy M3).
"""
import unittest
import shutil
from pathlib import Path
from decimal import Decimal
from fastapi.testclient import TestClient

from src.web.app import app
from src.skills.aml_tools import AMLVerificationEngine


class TestWebSettlement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Kopia zapasowa reguł kosztowych firmy domyślnej
        cls.rules_path = Path("firmy/5322030067-Smart_IT_Solutions_Arkadiusz_Cacko/reguly_kosztowe.json")
        cls.rules_backup = None
        if cls.rules_path.exists():
            cls.rules_backup = cls.rules_path.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        # Przywrócenie pierwotnych reguł kosztowych
        if cls.rules_backup is not None and cls.rules_path.exists():
            cls.rules_path.write_text(cls.rules_backup, encoding="utf-8")

    def setUp(self):
        AMLVerificationEngine.clear_cache()
        self.client = TestClient(app)

    def test_review_page_renders_successfully(self):
        """Test renderowania strony głównej przeglądu /przeglad."""
        response = self.client.get("/przeglad")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Sprawdzenie kluczowych sekcji KROK 2
        self.assertIn("Wstępny Przegląd i Akceptacja Dokumentów", html)
        self.assertIn("1. Tabela Faktur Przychodowych (Sprzedaż)", html)
        self.assertIn("2. Tabela Faktur Kosztowych (Zakupy)", html)
        self.assertIn("3. Rozstrzyganie Wątpliwości & Nauka Reguł Firmy", html)
        self.assertIn("Oświadczenie przedsiębiorcy", html)
        self.assertIn("confirm-revenues", html)
        self.assertIn("Gotowy do zamknięcia rozliczenia?", html)

    def test_costs_summary_endpoint(self):
        """Test pobierania paska sumy kosztów /api/costs/summary."""
        response = self.client.get("/api/costs/summary")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("costs-summary-bar", html)
        self.assertIn("Łączne koszty netto:", html)
        self.assertIn("VAT naliczony do odliczenia:", html)
        self.assertIn("zł", html)

    def test_qualify_expense_item_htmx(self):
        """Test zmiany kwalifikacji podatkowej wydatku (HTMX inline-editing)."""
        response = self.client.post(
            "/api/costs/qualify?lp=1&numer=FV/TEST/001",
            data={
                "kwalifikacja": "SAMOCHOD_50",
                "sprzedawca_nip": "5252545285",
                "opis": "Paliwo do samochodu służbowego",
                "zapisz_regule": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        # Sprawdzenie nagłówka wyzwalającego odświeżenie paska sum
        self.assertIn("HX-Trigger", response.headers)
        self.assertEqual(response.headers["HX-Trigger"], "update-costs-summary")

        html = response.text
        self.assertIn("expense-row-", html)
        self.assertIn("SAMOCHOD_50", html)

    def test_save_custom_rule(self):
        """Test utrwalania reguły kosztowej w reguly_kosztowe.json."""
        response = self.client.post(
            "/api/rules/save",
            data={
                "wzorzec": "Abonament Testowy Hosting",
                "kwalifikacja": "FIRMOWY_100",
                "sprzedawca_nip": "1234567890",
                "uzasadnienie": "Hosting serwera produkcyjnego",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Reguła została pomyślnie zapisana", html)

        # Sprawdzenie czy plik reguł faktycznie zawiera nowy wzorzec (zapisywany lowercase)
        saved_rules = self.rules_path.read_text(encoding="utf-8")
        self.assertIn("abonament testowy hosting", saved_rules.lower())

    def test_close_month_settlement_redirect(self):
        """Test finalizacji rozliczenia miesiąca i przekierowania do Pulpitu."""
        response = self.client.post(
            "/api/settlement/close",
            data={"nadwyzka_vat": "0.00"},
            follow_redirects=False,
        )
        # Oczekiwane przekierowanie 303 do /
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")


if __name__ == "__main__":
    unittest.main()
