"""
tests/test_web_invoices.py
Testy integracyjne Magazynu Faktur, Uploadu Drag&Drop, Ekstrakcji i KSeF (Kamień Milowy M5).
"""
import io
import json
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from src.web.app import app
from src.core.company import CompanyProfile
from src.level_1_ingestion.invoice_storage import InvoiceStorage


class TestWebInvoices(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.profile = CompanyProfile.load_by_nip("5322030067")
        self.created_test_files = []

    def tearDown(self):
        # Czyszczenie utworzonych plików testowych
        for p in self.created_test_files:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_invoices_dashboard_renders(self):
        """Test renderowania strony głównej magazynu faktur GET /faktury."""
        response = self.client.get("/faktury")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("Magazyn Dokumentów", html)
        self.assertIn("KROK 1", html)
        self.assertIn("KSeF 2.0", html)
        self.assertIn("Dodaj Faktury Spoza KSeF", html)
        self.assertIn("invoices-table-container", html)

    def test_invoices_tabs_filtering(self):
        """Test filtrowania zakładek: all, sprzedaz, koszty."""
        for tab in ["all", "sprzedaz", "koszty"]:
            resp = self.client.get(f"/faktury?tab={tab}")
            self.assertEqual(resp.status_code, 200)

    def test_upload_invalid_extension_rejected(self):
        """Test odrzucenia pliku z niedozwolonym rozszerzeniem (np. .exe)."""
        file_content = b"fake binary"
        response = self.client.post(
            "/faktury/upload",
            files={"file": ("virus.exe", file_content, "application/octet-stream")},
            data={"kategoria": "koszt"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Niedozwolony format pliku", response.text)

    def test_upload_valid_json_invoice_and_extraction(self):
        """Test uploadu poprawnej faktury JSON spoza KSeF i jej automatycznej ekstrakcji."""
        test_invoice_data = {
            "numer": "FV-TEST-WEB-M5-001",
            "data_wystawienia": "2026-01-15",
            "data_sprzedazy": "2026-01-15",
            "miejsce_wystawienia": "Warszawa",
            "sprzedawca": {
                "nazwa": "Hosting Provider Sp. z o.o.",
                "nip": "1234567890",
                "adres": "ul. Chmielna 1, Warszawa"
            },
            "nabywca": {
                "nazwa": self.profile.nazwa,
                "nip": self.profile.nip,
                "adres": "ul. Testowa 2, Warszawa"
            },
            "pozycje": [
                {
                    "opis": "Serwer Dedykowany Cloud",
                    "ilosc": 1,
                    "cena_jednostkowa_netto": 200.0,
                    "wartosc_netto": 200.0,
                    "stawka_vat": "23",
                    "kwota_vat": 46.0,
                    "wartosc_brutto": 246.0
                }
            ],
            "suma_netto": 200.0,
            "suma_vat": 46.0,
            "suma_brutto": 246.0,
            "waluta": "PLN",
            "typ": "koszt"
        }

        json_bytes = json.dumps(test_invoice_data, indent=2).encode("utf-8")
        filename = "test_invoice_m5_upload.json"

        response = self.client.post(
            "/faktury/upload",
            files={"file": (filename, json_bytes, "application/json")},
            data={"kategoria": "koszt"},
        )
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Sprawdzenie obecności sukcesu i zaimportowanej faktury
        self.assertIn("FV-TEST-WEB-M5-001", html)
        self.assertIn("Hosting Provider", html)
        self.assertIn("Przetworzono dokument pomyślnie", html)

        # Oznaczenie do usunięcia
        raw_file = InvoiceStorage.get_non_ksef_raw_dir(self.profile, "2026", "01", typ=None) / filename
        extracted_file = InvoiceStorage.get_non_ksef_extracted_dir(self.profile, "2026", "01", typ=None) / filename
        self.created_test_files.extend([raw_file, extracted_file])

    def test_safe_download_invoice_file(self):
        """Test bezpiecznego pobierania pliku dokumentu faktury."""
        # Utwórz plik testowy w katalogu firmy
        test_file = self.profile.katalog_firmy / "faktury" / "2026" / "01" / "test_download.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("Zawartosc testowa faktury", encoding="utf-8")
        self.created_test_files.append(test_file)

        response = self.client.get(f"/faktury/download?sciezka={test_file}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "Zawartosc testowa faktury")

    def test_path_traversal_attack_blocked(self):
        """Test zabezpieczenia przed atakiem Path Traversal (próba odczytu spoza katalogu firmy)."""
        response = self.client.get("/faktury/download?sciezka=/etc/passwd")
        # Oczekiwany kod 403 Forbidden
        self.assertEqual(response.status_code, 403)
        self.assertIn("Dostęp zabroniony", response.json()["detail"])

    def test_ksef_sync_endpoint_execution(self):
        """Test wywołania endpointu POST /faktury/ksef-sync."""
        response = self.client.post("/faktury/ksef-sync")
        self.assertEqual(response.status_code, 200)
        html = response.text
        # Sprawdzenie czy wygenerowano odpowiedź (sukces lub bezpiecznie przechwycony błąd KSeF)
        self.assertTrue("Synchronizacja KSeF" in html or "Krajowym Systemem e-Faktur" in html or "Brak skonfigurowanego tokenu" in html)


if __name__ == "__main__":
    unittest.main()
