"""
tests/test_web_invoices.py
Testy integracyjne Magazynu Faktur, Uploadu Drag&Drop, Ekstrakcji i KSeF (Kamień Milowy M5).
"""

import io
import json
import unittest

from fastapi.testclient import TestClient

from src.core.company import CompanyProfile
from src.level_1_ingestion.extraction_service import ExtractionService
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.web.app import app


class TestWebInvoices(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP

        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"
        self.profile = CompanyProfile.load_by_nip("7770001122")
        if not self.profile:
            from tests.fixtures import setup_test_company

            self.profile = setup_test_company()
        self.created_test_files = []
        if self.profile:
            ExtractionService.clear_task_status(self.profile, "2026", "01")
            ExtractionService.clear_task_status(self.profile, "2026", "04")

    def tearDown(self):
        if self.profile:
            ExtractionService.clear_task_status(self.profile, "2026", "01")
            ExtractionService.clear_task_status(self.profile, "2026", "04")
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
                "adres": "ul. Chmielna 1, Warszawa",
            },
            "nabywca": {"nazwa": self.profile.nazwa, "nip": self.profile.nip, "adres": "ul. Testowa 2, Warszawa"},
            "pozycje": [
                {
                    "opis": "Serwer Dedykowany Cloud",
                    "ilosc": 1,
                    "cena_jednostkowa_netto": 200.0,
                    "wartosc_netto": 200.0,
                    "stawka_vat": "23",
                    "kwota_vat": 46.0,
                    "wartosc_brutto": 246.0,
                }
            ],
            "suma_netto": 200.0,
            "suma_vat": 46.0,
            "suma_brutto": 246.0,
            "waluta": "PLN",
            "typ": "koszt",
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

    def test_upload_multiple_files_simultaneously(self):
        """Test jednoczesnego uploadu wielu plików (multi-file upload)."""
        f1_data = {
            "numer": "FV-MULTI-001",
            "data_wystawienia": "2026-01-10",
            "data_sprzedazy": "2026-01-10",
            "sprzedawca": {"nazwa": "Dostawca A", "nip": "1112223344"},
            "nabywca": {"nazwa": self.profile.nazwa, "nip": self.profile.nip},
            "pozycje": [
                {
                    "opis": "Usługa A",
                    "ilosc": 1,
                    "cena_jednostkowa_netto": 100.0,
                    "wartosc_netto": 100.0,
                    "stawka_vat": "23",
                    "kwota_vat": 23.0,
                    "wartosc_brutto": 123.0,
                }
            ],
            "suma_netto": 100.0,
            "suma_vat": 23.0,
            "suma_brutto": 123.0,
            "waluta": "PLN",
            "typ": "koszt",
        }
        f2_data = {
            "numer": "FV-MULTI-002",
            "data_wystawienia": "2026-01-11",
            "data_sprzedazy": "2026-01-11",
            "sprzedawca": {"nazwa": "Dostawca B", "nip": "9998887766"},
            "nabywca": {"nazwa": self.profile.nazwa, "nip": self.profile.nip},
            "pozycje": [
                {
                    "opis": "Usługa B",
                    "ilosc": 1,
                    "cena_jednostkowa_netto": 200.0,
                    "wartosc_netto": 200.0,
                    "stawka_vat": "23",
                    "kwota_vat": 46.0,
                    "wartosc_brutto": 246.0,
                }
            ],
            "suma_netto": 200.0,
            "suma_vat": 46.0,
            "suma_brutto": 246.0,
            "waluta": "PLN",
            "typ": "koszt",
        }

        files_payload = [
            ("files", ("f1.json", json.dumps(f1_data).encode("utf-8"), "application/json")),
            ("files", ("f2.json", json.dumps(f2_data).encode("utf-8"), "application/json")),
        ]
        response = self.client.post("/faktury/upload", files=files_payload, data={"kategoria": "koszt"})
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Przetworzono dokument pomyślnie", html)
        self.assertIn("f1.json", html)
        self.assertIn("f2.json", html)
        self.assertIn("FV-MULTI-001", html)
        self.assertIn("FV-MULTI-002", html)

        raw_dir = InvoiceStorage.get_non_ksef_raw_dir(self.profile, "2026", "01", typ=None)
        extracted_dir = InvoiceStorage.get_non_ksef_extracted_dir(self.profile, "2026", "01", typ=None)
        self.created_test_files.extend(
            [raw_dir / "f1.json", extracted_dir / "f1.json", raw_dir / "f2.json", extracted_dir / "f2.json"]
        )

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
        self.assertTrue(
            "Synchronizacja KSeF" in html
            or "Krajowym Systemem e-Faktur" in html
            or "Brak skonfigurowanego tokenu" in html
        )

    def test_unprocessed_invoices_banner_and_ai_extraction_flow(self):
        """Test wykrywania nieodczytanych faktur, wyświetlania ostrzeżenia i wywołania AI ekstrakcji."""
        # 1. Wywołanie GET /faktury dla 2026-04
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "04")

        # 2. Sprawdzenie endpointu POST /faktury/extract-ai
        resp_extract = self.client.post("/faktury/extract-ai")
        self.assertEqual(resp_extract.status_code, 200)
        self.assertIn("unprocessed-banner-container", resp_extract.text)

        # 3. Sprawdzenie endpointu GET /faktury/extract-status
        resp_status = self.client.get("/faktury/extract-status")
        self.assertEqual(resp_status.status_code, 200)
        self.assertIn("unprocessed-banner-container", resp_status.text)

        # 4. Sprawdzenie endpointu POST /faktury/extract-status/dismiss
        resp_dismiss = self.client.post("/faktury/extract-status/dismiss")
        self.assertEqual(resp_dismiss.status_code, 200)

    def test_upload_oob_banner_swap_and_guidance(self):
        """Test czy upload faktury zawiera OOB swap banera oraz wskazówkę o dodaniu kompletu plików."""
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "09")
        ExtractionService.clear_task_status(self.profile, "2026", "09")

        # Wgranie nieodczytywanego obrazu
        test_jpg_content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        files = [("files", ("test_unprocessed_upload.jpg", io.BytesIO(test_jpg_content), "image/jpeg"))]
        data = {"kategoria": "koszt"}

        response = self.client.post("/faktury/upload", files=files, data=data)
        self.assertEqual(response.status_code, 200)
        html = response.text

        # 1. Sprawdzenie czy jest OOB swap dla banera nieprzetworzonych dokumentów
        self.assertIn('id="unprocessed-banner-container"', html)
        self.assertIn('hx-swap-oob="true"', html)

        # 2. Sprawdzenie czy zawiera wskazówkę dla użytkownika o dodaniu kompletu dokumentów
        self.assertIn("dodaj najpierw wszystkie pliki", html)
        self.assertIn("po dodaniu kompletu dokumentów", html)

        # 3. Sprawdzenie czy przycisk AI ma hx-post do /faktury/extract-ai
        self.assertIn('hx-post="/faktury/extract-ai"', html)

        # Posprzątanie pliku
        raw_dir = InvoiceStorage.get_non_ksef_raw_dir(self.profile, "2026", "09", typ=None)
        self.created_test_files.append(raw_dir / "test_unprocessed_upload.jpg")
        ExtractionService.clear_task_status(self.profile, "2026", "09")

    def test_extract_ai_immediate_running_status(self):
        """Test czy kliknięcie 'Wyciągnij dane z faktury (AI)' natychmiast zwraca stan running ze spinnerem."""
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "01")

        response = self.client.post("/faktury/extract-ai")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # Odpowiedź musi od razu (synchronicznie) zawierać sekcję trwającego przetwarzania w tle
        self.assertIn("Trwa wyciąganie danych z faktur przez silnik AI", html)
        self.assertIn('hx-trigger="every 1500ms"', html)
        self.assertIn("Zadanie w tle", html)

    def test_extract_status_completed_triggers_table_refresh(self):
        """Test czy zakończenie ekstrakcji AI emituje nagłówek HX-Trigger oraz natychmiastowy OOB swap tabeli."""
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "01")

        ExtractionService.set_task_status(
            self.profile,
            "2026",
            "01",
            status="completed",
            message="Przetwarzanie zakończone testowo",
        )

        response = self.client.get("/faktury/extract-status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Trigger"), "invoices-refresh")
        self.assertIn("Zakończono wyciąganie danych z faktury!", response.text)
        # Weryfikacja bezpośredniego OOB swapu tabeli faktur
        self.assertIn('id="invoices-table-container"', response.text)
        self.assertIn('hx-swap-oob="true"', response.text)

    def test_invoices_table_partial_endpoint(self):
        """Test endpointu GET /faktury/table odpytywanego przez event invoices-refresh."""
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "01")

        response = self.client.get("/faktury/table?tab=all")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="invoices-table-container"', html)
        self.assertIn('hx-trigger="invoices-refresh from:body"', html)

    def test_extract_status_running_renders_progress_bar(self):
        """Test czy stan 'running' renderuje pasek postępu, licznik i aktualnie przetwarzany plik."""
        self.client.cookies.set("taxpilot_active_year", "2026")
        self.client.cookies.set("taxpilot_active_month", "01")

        ExtractionService.set_task_status(
            self.profile,
            "2026",
            "01",
            status="running",
            message="Przetwarzanie dokumentu 2 z 5...",
            current=2,
            total=5,
            percent=40,
            current_file="2026-05-paliwa10.jpg",
        )

        response = self.client.get("/faktury/extract-status")
        self.assertEqual(response.status_code, 200)
        html = response.text

        # 1. Sprawdzenie licznika
        self.assertIn("2 / 5 (40%)", html)
        # 2. Sprawdzenie nazwy aktualnego pliku
        self.assertIn("2026-05-paliwa10.jpg", html)
        # 3. Sprawdzenie paska postępu (width: 40%)
        self.assertIn("width: 40%", html)
        self.assertIn("40%", html)

    def test_upload_file_exceeds_15mb_returns_413(self):
        """Weryfikuje odrzucenie pliku przekraczającego limit 15 MB ze statusem 413 (SEC-2)."""
        # Utwórz strumień o rozmiarze 16 MB (16 * 1024 * 1024 bajtów)
        large_size = 16 * 1024 * 1024
        large_stream = io.BytesIO(b"%PDF-" + b"0" * (large_size - 5))

        response = self.client.post(
            "/faktury/upload",
            files={"file": ("duzy_dokument.pdf", large_stream, "application/pdf")},
            data={"kategoria": "koszt"},
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("Przekroczono dopuszczalny limit rozmiaru", response.text)
        self.assertIn("15 MB", response.text)

    def test_upload_fake_pdf_fails_magic_bytes(self):
        """Weryfikuje odrzucenie pliku .exe przemianowanego na .pdf (brak sygnatury %PDF-) ze statusem 400 (SEC-2)."""
        fake_pdf_content = b"MZ\x90\x00\x03\x00\x00\x00This is a Windows executable!"
        response = self.client.post(
            "/faktury/upload",
            files={"file": ("faktura_falszywa.pdf", fake_pdf_content, "application/pdf")},
            data={"kategoria": "koszt"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Brak poprawnej sygnatury PDF", response.text)

    def test_upload_fake_image_fails_magic_bytes(self):
        """Weryfikuje odrzucenie pliku tekstowego przemianowanego na .png ze statusem 400 (SEC-2)."""
        fake_png_content = b"To nie jest plik graficzny PNG!"
        response = self.client.post(
            "/faktury/upload",
            files={"file": ("falszywy_skan.png", fake_png_content, "image/png")},
            data={"kategoria": "koszt"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Brak poprawnej sygnatury obrazu PNG", response.text)

    def test_sanitize_filename_utility(self):
        """Weryfikuje działanie sanityzacji nazw plików (usunięcie path traversal i znaków specjalnych)."""
        from src.web.routers.invoices import sanitize_filename

        self.assertEqual(sanitize_filename("../../etc/passwd.pdf"), "passwd.pdf")
        self.assertEqual(sanitize_filename("Faktura VAT 12-2026.pdf"), "Faktura_VAT_12-2026.pdf")
        self.assertEqual(sanitize_filename("skan@#$!*()___.png"), "skan.png")
        self.assertEqual(sanitize_filename("..///..///test.json"), "test.json")


if __name__ == "__main__":
    unittest.main()
