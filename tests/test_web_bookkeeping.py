"""
tests/test_web_bookkeeping.py
Testy jednostkowe i integracyjne dla nowego modułu Księgowanie (/ksiegowanie).
"""
import unittest
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.core.company import CompanyProfile, FormaOpodatkowania, TypZUS, ZUSConfig
from src.core.invoice import Invoice, InvoiceType, InvoiceItem, InvoiceParty
from src.web.app import app


class TestWebBookkeeping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP
        cls.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="taxpilot_test_bookkeeping_"))

        from tests.fixtures import setup_test_company
        cls.profile = setup_test_company()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_bookkeeping_dashboard_renders_cleanly(self):
        """GET /ksiegowanie zwraca status 200 i poprawne sekcje ewidencji."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]):
            response = self.client.get("/ksiegowanie")
            assert response.status_code == 200
            html = response.text
            assert "Księgowanie &amp; Ewidencje Podatkowe" in html or "Księgowanie" in html
            assert "Podsumowanie Dokumentów Przeznaczonych do Księgowania" in html
            assert "Ewidencja Przychodów (Ryczałt)" in html
            assert "Ewidencja Kosztów (Zakupy)" in html
            assert "Rejestry VAT" in html
            assert "Paczka Przelewów Podatnika" in html
            assert "Sprawozdanie &amp; Audyt" in html or "Sprawozdanie & Audyt" in html
            assert "Sprawozdanie &amp; Audyt (Markdown)" not in html
            assert "Sprawozdanie & Audyt (Markdown)" not in html

    def test_bookkeeping_cost_ledger_tab_with_invoices(self):
        """GET /ksiegowanie?tab=koszty poprawnie renderuje zakładkę ewidencji kosztów."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]):
            response = self.client.get("/ksiegowanie?tab=koszty")
            assert response.status_code == 200
            html = response.text
            assert "Oficjalna Ewidencja Kosztów i Zakupów" in html
            assert "KUP Netto (Koszty)" in html
            assert "VAT do Odliczenia" in html
            assert "Wykluczenia Prywatne" in html

    def test_execute_settlement_ajax_endpoint(self):
        """POST /ksiegowanie/uruchom przez AJAX zwraca JSON ze statusem sukcesu."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]), \
             patch("src.level_3_tax_settlement.settlement_service.SettlementService.settle_month"):
            response = self.client.post(
                "/ksiegowanie/uruchom",
                data={"nadwyzka_vat": "200.00"},
                headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "został pomyślnie zaksięgowany" in data["message"]

    def test_bookkeeping_markdown_rendering_html_tables(self):
        """Sprawdza czy markdown zamienia się na tabele HTML w podglądzie sprawozdań."""
        sample_bundle = {
            "settlement": {"przychod_roczny_narastajaco": "10000.00", "przelewy": []},
            "ewidencja_md": "# Ewidencja",
            "ewidencja_sumy_md": "# Ewidencja Sumy\n\n| Miesiąc | Przychód |\n| :---: | ---: |\n| `01/2026` | 1000.00 zł |\n",
            "sprawozdanie_md": "# Sprawozdanie Audytu\n\n- Punkt 1\n- Punkt 2\n",
            "rozliczenie_md": "# Rozliczenie",
        }
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]), \
             patch("src.web.routers.bookkeeping._load_settlement_bundle", return_value=sample_bundle):
            response = self.client.get("/ksiegowanie?tab=ytd")
            assert response.status_code == 200
            html = response.text
            assert "<table" in html
            assert "01/2026" in html
            assert "<pre class=\"bg-slate-900 text-slate-100" not in html
            assert "<ul class=\"list-disc" in html

    def test_bookkeeping_cost_ledger_tab_with_invoices(self):
        """GET /ksiegowanie?tab=koszty poprawnie renderuje zakładkę ewidencji kosztów."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]):
            response = self.client.get("/ksiegowanie?tab=koszty")
            assert response.status_code == 200
            html = response.text
            assert "Oficjalna Ewidencja Kosztów i Zakupów" in html
            assert "KUP Netto (Koszty)" in html
            assert "VAT do Odliczenia" in html
            assert "Wykluczenia Prywatne" in html

    def test_execute_settlement_endpoint(self):
        """POST /ksiegowanie/uruchom uruchamia deterministyczne księgowanie."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]), \
             patch("src.level_3_tax_settlement.settlement_service.SettlementService.settle_month") as mock_settle:
            response = self.client.post(
                "/ksiegowanie/uruchom",
                data={"nadwyzka_vat": "150.00"},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/ksiegowanie?sukces=1"
            mock_settle.assert_called_once()
            call_kwargs = mock_settle.call_args.kwargs
            assert call_kwargs["nadwyzka_vat_poprzedni"] == Decimal("150.00")

    def test_invoices_table_file_preview_button(self):
        """GET /faktury wyświetla przycisk podglądu pliku w kolumnie Plik tabeli dokumentów."""
        inv = Invoice(
            numer="FV/TEST/001",
            data_wystawienia="2026-10-10",
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            sprzedawca=InvoiceParty(nazwa="Dostawca", nip="1234567890"),
            nabywca=InvoiceParty(nazwa=self.profile.nazwa, nip=self.profile.nip),
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
        )
        inv.plik_zrodlowy = "faktura_123.pdf"

        mock_summary = {
            "invoices": [inv],
            "sprzedaz": [],
            "koszty": [inv],
            "suma_sprzedaz_netto": Decimal("0.00"),
            "suma_sprzedaz_vat": Decimal("0.00"),
            "suma_koszty_netto": Decimal("100.00"),
            "suma_koszty_vat": Decimal("23.00"),
            "ksef_count": 0,
            "non_ksef_count": 1,
            "relokacje": [],
        }

        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]), \
             patch("src.web.routers.invoices.get_month_invoices_summary", return_value=mock_summary):
            response = self.client.get("/faktury")
            assert response.status_code == 200
            assert 'hx-get="/api/invoices/preview' in response.text
            assert 'faktura_123.pdf' in response.text
            assert 'id="invoice-modal-container"' in response.text

    def test_invoice_preview_displays_file_path(self):
        """GET /api/invoices/preview zwraca modal z widoczną ścieżką do pliku."""
        inv = Invoice(
            numer="FV/TEST/2026/01",
            data_wystawienia="2026-10-10",
            typ=InvoiceType.KOSZT,
            zrodlo="NON_KSEF",
            sprzedawca=InvoiceParty(nazwa="Hosting Cloud Sp. z o.o.", nip="5213242793"),
            nabywca=InvoiceParty(nazwa=self.profile.nazwa, nip=self.profile.nip),
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
            pozycje=[
                InvoiceItem(
                    opis="Serwer VPS",
                    ilosc=Decimal("1"),
                    cena_jednostkowa_netto=Decimal("100.00"),
                    wartosc_netto=Decimal("100.00"),
                    stawka_vat=Decimal("23"),
                    kwota_vat=Decimal("23.00"),
                    wartosc_brutto=Decimal("123.00"),
                )
            ]
        )
        inv.plik_zrodlowy = "/sciezka/do/faktury/FV_TEST.json"

        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]), \
             patch("src.level_1_ingestion.invoice_storage.InvoiceStorage.list_invoices", return_value=[inv]):
            response = self.client.get("/api/invoices/preview?numer=FV/TEST/2026/01&typ=koszty")
            assert response.status_code == 200
            html = response.text
            assert "FV/TEST/2026/01" in html
            assert "Ścieżka do pliku:" in html
            assert "/sciezka/do/faktury/FV_TEST.json" in html
            assert "Kopiuj ścieżkę" in html

    def test_bookkeeping_displays_zus_indicators_tab(self):
        """GET /ksiegowanie wyświetla nową zakładkę wskaźników ZUS/GUS oraz wyliczone składki."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]):
            response = self.client.get("/ksiegowanie")
            assert response.status_code == 200
            html = response.text
            assert "Wskaźniki ZUS / GUS" in html
            assert "Podstawa Pełny ZUS" in html
            assert "5652.00" in html
            assert "Przeciętne Wynagrodzenie IV kw." in html
            assert "9228.64" in html
            assert "Zestawienie Składek na Ubezpieczenia Społeczne" in html
            assert "Składka Zdrowotna na Ryczałcie dla Roku" in html

    def test_bookkeeping_prompts_and_saves_zus_indicators_for_new_year(self):
        """Gdy w wyniku zmiany roku brak oficjalnych wskaźników (np. 2027), system wyświetla monit i pozwala zapisać."""
        with patch("src.web.dependencies.get_active_profile", return_value=self.profile), \
             patch("src.web.dependencies.get_all_companies", return_value=[self.profile]):
            
            # 1. Wejście z rokiem 2027 -> Monit o uzupełnienie wskaźników
            self.client.cookies.set("taxpilot_active_year", "2027")
            resp1 = self.client.get("/ksiegowanie")
            assert resp1.status_code == 200
            assert "Wymagana weryfikacja / uzupełnienie wskaźników ZUS na rok 2027" in resp1.text
            assert "Prognoza szacunkowa" in resp1.text or "automatycznej prognozie szacunkowej" in resp1.text

            # 2. Zapisanie uzupełnionych wskaźników dla roku 2027
            resp_save = self.client.post(
                "/ksiegowanie/wskazniki-zus",
                data={
                    "rok": "2027",
                    "podstawa_pelny_zus": "5750.00",
                    "podstawa_preferencyjny_zus": "1550.00",
                    "przecietne_wynagrodzenie_zdrowotna": "9650.00",
                },
                follow_redirects=False,
            )
            assert resp_save.status_code == 303
            assert resp_save.headers["location"] == "/ksiegowanie?wskazniki_zapisane=1&tab=wskazniki"

            # 3. Ponowne wejście -> Wskaźniki są zatwierdzone, brak monitu ostrzegawczego
            resp2 = self.client.get("/ksiegowanie?tab=wskazniki")
            assert resp2.status_code == 200
            assert "5750.00" in resp2.text
            assert "9650.00" in resp2.text
            assert "Zatwierdzone / Oficjalne" in resp2.text
            # Monit o konieczności uzupełnienia nie pojawia się już jako ostrzeżenie
            assert "Wymagana weryfikacja / uzupełnienie wskaźników ZUS na rok 2027" not in resp2.text

            # Sprzątanie testowego wpisu 2027 z cache, aby nie zaśmiecać stanu aplikacji
            import json
            cache_file = Path("data/wskazniki_zus_cache.json")
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                if "2027" in cdata:
                    del cdata["2027"]
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cdata, f, indent=2, ensure_ascii=False)
