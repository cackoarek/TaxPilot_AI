"""
tests/test_web_settlement.py
Testy integracyjne modułu Wstępnego Przeglądu i Akceptacji Dokumentów (Pre-settlement Review - Kamień Milowy M3).
"""

import unittest
from decimal import Decimal

from fastapi.testclient import TestClient

from src.skills.aml_tools import AMLVerificationEngine
from src.web.app import app


class TestWebSettlement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.fixtures import setup_isolated_test_company

        cls.profile = setup_isolated_test_company()

    @classmethod
    def tearDownClass(cls):
        from tests.fixtures import cleanup_test_company

        cleanup_test_company(cls.profile)

    def setUp(self):
        AMLVerificationEngine.clear_cache()
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP

        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"

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
        self.assertIn("Compliance AML & VAT", html)
        # Zgodnie z wytycznymi z work-session-06: usunięto kolumnę/wzmianki AML z tabel w widoku przeglądu
        self.assertNotIn("Status AML", html)

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
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "01" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-01 dla firmy testowej")
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

    def test_qualify_expense_item_overrides_unapproved_ai_suggestion(self):
        """Wybór użytkownika (np. SAMOCHOD_50) ma bezwzględne pierwszeństwo przed niezatwierdzoną sugestią AI (FIRMOWY_100)."""
        p_path = self.profile.katalog_firmy
        if not (p_path / "faktury" / "2026" / "01" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-01 dla firmy testowej")
        from src.core.company import CompanyProfile
        from src.web.services.ai_cost_qualifier import AICostQualifierService, AIQualificationItem

        profile = CompanyProfile.load_from_dir(p_path)

        # Symulacja istnienia niezatwierdzonej sugestii AI FIRMOWY_100 dla realnej faktury 43/1/2026 (LP 9)
        sugestie = {
            "43/1/2026::zakup z pliku 2026-01-samochod-fv 43-1-2026.pdf": AIQualificationItem(
                numer_faktury="43/1/2026",
                sprzedawca_nazwa="ACME INC",
                sprzedawca_nip="5252545285",
                pozycja_opis="Zakup z pliku 2026-01-samochod-FV 43-1-2026.pdf",
                kwota_netto=Decimal("100.00"),
                kwota_vat=Decimal("23.00"),
                kwalifikacja_sugerowana="FIRMOWY_100",
                porada_ksiegowa="AI zasugerowało 100%",
                zatwierdzony=False,
            )
        }
        AICostQualifierService.save_suggestions(profile, "2026", "01", sugestie)

        # Użytkownik zmienia kwalifikację na SAMOCHOD_50
        response = self.client.post(
            "/api/costs/qualify?lp=9&numer=43/1/2026",
            data={
                "kwalifikacja": "SAMOCHOD_50",
                "sprzedawca_nip": "5252545285",
                "opis": "Zakup z pliku 2026-01-samochod-FV 43-1-2026.pdf",
                "zapisz_regule": "false",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.text
        # Upewnij się, że nie powróciło do 100%, lecz wybrano 50%
        self.assertIn('value="SAMOCHOD_50" selected', html)
        self.assertNotIn('value="FIRMOWY_100" selected', html)

    def test_save_custom_rule(self):
        """Test utrwalania reguły kosztowej w reguly_kosztowe.json."""
        rules_path = self.profile.katalog_firmy / "reguly_kosztowe.json"
        if not rules_path.exists():
            self.skipTest("Brak pliku reguly_kosztowe.json dla firmy testowej")
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
        saved_rules = rules_path.read_text(encoding="utf-8")
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

    def test_intelligent_audit_run_endpoint(self):
        """Test endpointu inteligentnego audytu POST /api/costs/audit-run."""
        response = self.client.post("/api/costs/audit-run")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("audit-result-banner", html)
        self.assertIn("Wynik Inteligentnego Audytu Podatkowego", html)
        self.assertIn("Poprawność Folderów", html)
        self.assertIn("Zasadność Gospodarcza (PKD)", html)
        self.assertIn("HX-Trigger", response.headers)
        self.assertEqual(response.headers["HX-Trigger"], "refresh-review-tables")

    def test_qualify_single_position_endpoint(self):
        """Test zmiany kwalifikacji konkretnej pozycji POST /api/costs/qualify-item."""
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "01" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-01 dla firmy testowej")
        response = self.client.post(
            "/api/costs/qualify-item?numer=FV/TEST/001&item_idx=0&lp=1",
            data={
                "kwalifikacja": "PRYWATNY_0",
                "opis": "Telewizja PLAY NOW - pakiet",
                "sprzedawca_nip": "9512120077",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("HX-Trigger", response.headers)
        self.assertEqual(response.headers["HX-Trigger"], "update-costs-summary")
        html = response.text
        self.assertIn("expense-block-", html)

    def test_invoice_preview_modal_endpoint(self):
        """Test endpointu podglądu faktury GET /api/invoices/preview (uproszczony + JSON)."""
        # Sprawdzenie dla istniejącej faktury w zestawieniu
        rev_res = self.client.get("/przeglad")
        self.assertEqual(rev_res.status_code, 200)

        # Upewnienie się, że w DOM jest dokładnie jeden kontener modalu #invoice-modal-container
        self.assertEqual(rev_res.text.count('id="invoice-modal-container"'), 1)
        self.assertIn("window.Alpine.initTree(evt.detail.target)", rev_res.text)

        # Wywołanie dla przykładowego numeru (lub 404 dla nieistniejącego)
        response_404 = self.client.get("/api/invoices/preview?numer=NIEISTNIEJACA_FAKTURA_999&typ=koszty")
        self.assertEqual(response_404.status_code, 404)

    def test_review_renders_clarification_section_when_ambiguous(self):
        """Test czy pozycje wymagające wyjaśnienia są wyraźnie oznaczone w widoku /przeglad."""
        response = self.client.get("/przeglad?rok=2026&miesiac=10")
        self.assertEqual(response.status_code, 200)
        html = response.text
        if "Wykryto" in html and "do wyjaśnienia" in html:
            self.assertIn("Wymagana decyzja", html)
            self.assertIn("Co należy wyjaśnić?", html)

    def test_ai_qualify_endpoints(self):
        """Test uruchomienia kwalifikacji faktur AI i sprawdzania statusu."""
        # Uruchomienie kwalifikacji
        run_res = self.client.post("/api/costs/ai-qualify-run")
        self.assertEqual(run_res.status_code, 200)
        self.assertIn("ai-qualify-banner", run_res.text)

        # Sprawdzenie statusu
        status_res = self.client.get("/api/costs/ai-qualify-status")
        self.assertEqual(status_res.status_code, 200)
        self.assertIn("ai-qualify-banner", status_res.text)

    def test_approve_expense_endpoints(self):
        """Test zatwierdzania faktury i pozycji kosztowej."""
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "01" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-01 dla firmy testowej")
        # Test zatwierdzenia całej faktury
        res = self.client.post("/api/costs/approve?numer=FV/TEST/001&lp=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("HX-Trigger", res.headers)
        self.assertIn("expense-row-", res.text)

        # Test zatwierdzenia konkretnej pozycji
        item_res = self.client.post("/api/costs/approve-item?numer=FV/TEST/001&item_idx=0&lp=1")
        self.assertEqual(item_res.status_code, 200)
        self.assertIn("HX-Trigger", item_res.headers)
        self.assertIn("expense-block-", item_res.text)

    def test_approve_item_with_private_zero_does_not_create_rule_and_preserves_zero(self):
        """Zatwierdzenie pozycji z kwalifikacją PRYWATNY_0 nie tworzy trwałej reguły i zachowuje 0% odliczenia."""
        p_path = self.profile.katalog_firmy
        if not (p_path / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        from src.core.company import CompanyProfile
        from src.skills.cost_classifier import ReczneKwalifikacjeService, RegulyKosztoweFirmy
        from src.web.services.ai_cost_qualifier import AICostQualifierService, AIQualificationItem

        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})
        profile = CompanyProfile.load_from_dir(p_path)

        test_num = "FV/TEST/PRYW_999"
        test_opis = "Pakiet filmowy prywatny test"

        # Symulacja sugestii AI dla pozycji
        sugestie = {
            f"{test_num}::{test_opis.lower()}": AIQualificationItem(
                numer_faktury=test_num,
                sprzedawca_nazwa="Test VOD Sp. z o.o.",
                sprzedawca_nip="1112223344",
                pozycja_opis=test_opis,
                kwota_netto=Decimal("50.00"),
                kwota_vat=Decimal("11.50"),
                kwalifikacja_sugerowana="PRYWATNY_0",
                porada_ksiegowa="Wydatek osobisty bez związku z działalnością IT",
                zatwierdzony=False,
            )
        }
        AICostQualifierService.save_suggestions(profile, "2026", "10", sugestie)

        # Zatwierdzenie pozycji (odpowiada kliknięciu 'Zatwierdź' przy sugestii PRYWATNY_0)
        res = self.client.post(
            f"/api/costs/approve-item?numer={test_num}&item_idx=0&lp=1&opis={test_opis}&kwalifikacja=PRYWATNY_0&rok=2026&miesiac=10"
        )
        self.assertEqual(res.status_code, 200)

        # 1. Reguła NIE może trafić do reguly_kosztowe.json
        reguly = RegulyKosztoweFirmy.load(profile)
        for r in reguly.reguly_globalne:
            self.assertNotEqual(r.wzorzec.lower(), test_opis.lower())
        for nip_k, r_list in reguly.reguly_kontrahentow.items():
            for r in r_list:
                self.assertNotEqual(r.wzorzec.lower(), test_opis.lower())

        # 2. Decyzja musi być zapisana w miesięcznych nadpisaniach (reczne_kwalifikacje.json) jako PRYWATNY_0
        overrides = ReczneKwalifikacjeService.load_overrides(profile, "2026", "10")
        klucz = f"{test_num}::{test_opis.lower()}"
        self.assertIn(klucz, overrides)
        self.assertEqual(overrides[klucz]["kwalifikacja"], "PRYWATNY_0")

    def test_sales_table_percentage_and_tooltip(self):
        """Test czy stawka ryczałtu jest sformatowana jako procent i tooltip z pełnym opisem."""
        res = self.client.get("/przeglad?rok=2026&miesiac=04")
        self.assertEqual(res.status_code, 200)
        html = res.text
        # W tabeli sprzedaży stawka ryczałtu powinna mieć format np. 12%
        self.assertIn("12%", html)
        self.assertIn('title="', html)

    def test_copilot_history_endpoint(self):
        """Test endpointu historii Copilota GET /api/copilot/history."""
        from unittest.mock import MagicMock

        from src.web.dependencies import get_global_context
        from src.web.routers.copilot import ChatSessionManager, CopilotSessionHistory

        # Dynamiczne pobranie profilu i powiązanego identyfikatora sesji
        ctx = get_global_context(MagicMock(query_params={}, cookies=self.client.cookies))
        profile = ctx.get("profile")
        rok = ctx.get("rok", "2026")
        miesiac = ctx.get("miesiac", "01")
        nip = profile.nip if profile else "default"
        session_id = f"company_{nip}"

        # Upewnienie się, że aktywna sesja jest pusta (zarówno ChatSessionManager jak i CopilotSessionHistory)
        active_session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac) if profile else None
        if active_session:
            active_session.messages = []
            ChatSessionManager.save_session(profile, active_session)
        CopilotSessionHistory.clear(session_id)

        # Gdy pusta historia
        res = self.client.get("/api/copilot/history")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "")

        # Po dodaniu wiadomości do sesji
        CopilotSessionHistory.add_message(session_id, "Testowe pytanie do asystenta")
        res_with_msg = self.client.get("/api/copilot/history")
        self.assertEqual(res_with_msg.status_code, 200)
        self.assertIn("Testowe pytanie do asystenta", res_with_msg.text)
        self.assertIn("copilot-active-loader", res_with_msg.text)

        # Sprzątanie po teście
        CopilotSessionHistory.clear(session_id)
        if active_session:
            active_session.messages = []
            ChatSessionManager.save_session(profile, active_session)

    def test_qualify_samochod_50_selection_not_reverting_to_zero(self):
        """Test czy wybór SAMOCHOD_50 (np. dla faktury Orlen F 37804/1561/26) zaznacza wyłącznie 50% i nie dubluje 0%."""
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})
        res = self.client.post(
            "/api/costs/qualify?lp=7&numer=F%2037804/1561/26",
            data={
                "kwalifikacja": "SAMOCHOD_50",
                "sprzedawca_nip": "7740001454",
                "opis": "EFECTA 95 CN27101245",
                "zapisz_regule": "true",
            },
        )
        self.assertEqual(res.status_code, 200)
        html = res.text
        # Upewnij się, że opcja SAMOCHOD_50 jest oznaczona jako selected
        self.assertIn('value="SAMOCHOD_50" selected', html)
        # Opcja PRYWATNY_0 NIE może zawierać selected
        self.assertNotIn('value="PRYWATNY_0" selected', html)
        self.assertNotIn('value="FIRMOWY_100" selected', html)

    def test_multi_position_rule_isolation_play_invoice(self):
        """Test czy zmiana kwalifikacji ogólnej pozycji 'Usługi telekomunikacyjne' nie nadpisuje 'Usługi telekomunikacyjne – TV'."""
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})
        # Najpierw upewnij się, że reguła dla TV jest PRYWATNY_0
        self.client.post(
            "/api/costs/qualify-item?numer=F/60131422/10/26&item_idx=0&lp=10",
            data={
                "kwalifikacja": "PRYWATNY_0",
                "opis": "Usługi telekomunikacyjne – TV",
                "sprzedawca_nip": "9512120077",
            },
        )
        # Następnie zmień Usługi telekomunikacyjne na FIRMOWY_100
        res = self.client.post(
            "/api/costs/qualify-item?numer=F/60131422/10/26&item_idx=2&lp=10",
            data={
                "kwalifikacja": "FIRMOWY_100",
                "opis": "Usługi telekomunikacyjne",
                "sprzedawca_nip": "9512120077",
            },
        )
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Sprawdzenie w wyrenderowanym bloku tabeli:
        # 1. Pozycja 'Usługi telekomunikacyjne – TV' musi mieć wybraną opcję PRYWATNY_0
        self.assertIn("Usługi telekomunikacyjne – TV", html)
        # 2. Pozycja 'Usługi telekomunikacyjne' musi mieć wybraną opcję FIRMOWY_100
        self.assertIn("Usługi telekomunikacyjne", html)
        # 3. Wiersz podpozycji dla TV musi mieć PRYWATNY_0 selected
        pos_idx = html.find('value="Usługi telekomunikacyjne – TV"')
        self.assertNotEqual(pos_idx, -1)
        tr_start = html.rfind("<tr", 0, pos_idx)
        tr_end = html.find("</tr>", pos_idx)
        tv_row = html[tr_start:tr_end]
        self.assertIn("Usługi telekomunikacyjne – TV", tv_row)
        self.assertIn('value="PRYWATNY_0" selected', tv_row)
        self.assertNotIn('value="FIRMOWY_100" selected', tv_row)

    def test_qualify_selection_does_not_create_permanent_rule(self):
        """Wybór opcji w <select> nie może tworzyć stałej reguły w reguly_kosztowe.json, a jedynie miesięczny override."""
        from src.core.company import CompanyProfile
        from src.skills.cost_classifier import ReczneKwalifikacjeService, RegulyKosztoweFirmy

        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile or not (profile.katalog_firmy / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})

        # Usunięcie ewentualnej wcześniejszej reguły testowej
        reguly_przed = RegulyKosztoweFirmy.load(profile)
        reguly_przed.usun_regule(profile, "specyficzny_testowy_wydatek_xyz", "7740001454")

        # Zmiana kwalifikacji przez select inline (bez przycisku reguły)
        res = self.client.post(
            "/api/costs/qualify?lp=1&numer=FV/TEST/XYZ_999",
            data={
                "kwalifikacja": "SAMOCHOD_50",
                "sprzedawca_nip": "7740001454",
                "opis": "specyficzny_testowy_wydatek_xyz",
            },
        )
        self.assertEqual(res.status_code, 200)

        # 1. Reguła NIE może powstać w reguly_kosztowe.json
        reguly_po = RegulyKosztoweFirmy.load(profile)
        pasujace_reguly = [
            r for r in reguly_po.pobierz_wszystkie_reguly() if "specyficzny_testowy_wydatek_xyz" in r["wzorzec"]
        ]
        self.assertEqual(
            len(pasujace_reguly), 0, "Wybór w <select> nie powinien tworzyć reguły w reguly_kosztowe.json!"
        )

        # 2. Miesięczny override MUSI powstać w reczne_kwalifikacje.json
        overrides = ReczneKwalifikacjeService.load_overrides(profile, "2026", "10")
        self.assertTrue(
            any("XYZ_999" in k for k in overrides.keys()),
            "Miesięczny override powinien zostać zapisany w reczne_kwalifikacje.json",
        )

    def test_save_rule_from_item_button_creates_permanent_rule(self):
        """Kliknięcie dedykowanego przycisku 'Reguła' (POST /api/rules/save-from-item) tworzy stałą regułę firmy."""
        from src.core.company import CompanyProfile
        from src.skills.cost_classifier import RegulyKosztoweFirmy

        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile or not (profile.katalog_firmy / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})

        # Usunięcie reguły jeśli istniała
        reguly = RegulyKosztoweFirmy.load(profile)
        reguly.usun_regule(profile, "paliwo_vpower_racing_99", "7740001454")

        res = self.client.post(
            "/api/rules/save-from-item",
            data={
                "lp": 1,
                "numer": "F 9999/TEST/26",
                "kwalifikacja": "SAMOCHOD_50",
                "opis": "paliwo_vpower_racing_99",
                "sprzedawca_nip": "7740001454",
                "uzasadnienie": "Paliwo do samochodu służbowego",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("Zapisano stałą regułę", res.text)

        # Reguła musi teraz istnieć w reguly_kosztowe.json
        reguly_po = RegulyKosztoweFirmy.load(profile)
        pasujace = [r for r in reguly_po.pobierz_wszystkie_reguly() if "paliwo_vpower_racing_99" in r["wzorzec"]]
        self.assertEqual(len(pasujace), 1)
        self.assertEqual(pasujace[0]["kwalifikacja"], "SAMOCHOD_50")

    def test_rules_list_and_delete_endpoints(self):
        """Test wyświetlania listy reguł GET /api/rules/list oraz usuwania POST /api/rules/delete."""
        from src.core.company import CompanyProfile
        from src.skills.cost_classifier import KwalifikacjaKosztu, RegulyKosztoweFirmy

        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile or not (profile.katalog_firmy / "reguly_kosztowe.json").exists():
            self.skipTest("Brak pliku reguł kosztowych dla firmy testowej")

        reguly = RegulyKosztoweFirmy.load(profile)
        reguly.dodaj_regule(
            profile=profile,
            wzorzec="test_do_usuniecia_123",
            kwalifikacja=KwalifikacjaKosztu.PRYWATNY_0,
            uzasadnienie="Reguła testowa",
            nip_kontrahenta="9999999999",
        )

        # 1. Pobranie listy reguł
        res_list = self.client.get("/api/rules/list")
        self.assertEqual(res_list.status_code, 200)
        self.assertIn("test_do_usuniecia_123", res_list.text)
        self.assertIn("9999999999", res_list.text)
        self.assertIn("Usuń", res_list.text)

        # 2. Usunięcie reguły
        res_del = self.client.post(
            "/api/rules/delete",
            data={
                "wzorzec": "test_do_usuniecia_123",
                "sprzedawca_nip": "9999999999",
            },
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertIn("Usunięto regułę", res_del.text)
        tbody_part = (
            res_del.text[res_del.text.find("<tbody") : res_del.text.find("</tbody>")]
            if "<tbody" in res_del.text
            else ""
        )
        self.assertNotIn("test_do_usuniecia_123", tbody_part)

        # Upewnienie się, że w pliku reguła zniknęła
        reguly_po = RegulyKosztoweFirmy.load(profile)
        pasujace = [r for r in reguly_po.pobierz_wszystkie_reguly() if "test_do_usuniecia_123" in r["wzorzec"]]
        self.assertEqual(len(pasujace), 0)

    def test_bulk_qualify_all_items_when_more_than_5_positions(self):
        """
        Test zbiorczej kwalifikacji dla faktur z > 5 pozycji:
        1. W widoku /przeglad faktura z 16 pozycjami (6550172) ma pasek zbiorczej kwalifikacji.
        2. Faktura z 4 pozycjami (F/60131422/10/26) NIE ma paska zbiorczej kwalifikacji.
        3. Endpoint POST /api/costs/qualify-all-items ustawia kwalifikację dla wszystkich pozycji jednocześnie.
        """
        if not (self.profile.katalog_firmy / "faktury" / "2026" / "10" / "koszty").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        # Ustawienie okresu 2026-10
        self.client.post("/firmy/period", data={"rok": "2026", "miesiac": "10"})

        # 1. Sprawdzenie widoku /przeglad
        res_review = self.client.get("/przeglad?rok=2026&miesiac=10")
        self.assertEqual(res_review.status_code, 200)
        html = res_review.text

        # Faktura 6550172 (16 pozycji) powinna zawierać pasek zbiorczej kwalifikacji
        self.assertIn("Faktura wielopozycyjna (16 pozycji) – Zbiorcza kwalifikacja", html)
        self.assertIn("/api/costs/qualify-all-items?numer=6550172", html)
        self.assertIn("Wszystkie: 100%", html)
        self.assertIn("Wszystkie: 50%", html)
        self.assertIn("Wszystkie: 0%", html)

        # Faktura F/60131422/10/26 (4 pozycje) NIE powinna mieć paska zbiorczego
        self.assertNotIn("Faktura wielopozycyjna (4 pozycji) – Zbiorcza kwalifikacja", html)

        # 2. Test zbiorczego ustawienia SAMOCHOD_50
        res_bulk_50 = self.client.post("/api/costs/qualify-all-items?numer=6550172&lp=1&kwalifikacja=SAMOCHOD_50")
        self.assertEqual(res_bulk_50.status_code, 200)
        html_50 = res_bulk_50.text
        # Wszystkie opcje powinny być teraz wybrane jako SAMOCHOD_50
        self.assertIn("🚗 50% Samochód", html_50)
        self.assertIn("update-costs-summary", res_bulk_50.headers.get("HX-Trigger", ""))

        # 3. Test zbiorczego ustawienia PRYWATNY_0
        res_bulk_0 = self.client.post("/api/costs/qualify-all-items?numer=6550172&lp=1&kwalifikacja=PRYWATNY_0")
        self.assertEqual(res_bulk_0.status_code, 200)
        html_0 = res_bulk_0.text
        self.assertIn("⛔ 0% Prywatny", html_0)
        self.assertIn("Odliczenie: <strong>0.00 zł</strong>", html_0)

        # 4. Test zbiorczego powrotu do FIRMOWY_100
        res_bulk_100 = self.client.post("/api/costs/qualify-all-items?numer=6550172&lp=1&kwalifikacja=FIRMOWY_100")
        self.assertEqual(res_bulk_100.status_code, 200)
        html_100 = res_bulk_100.text
        self.assertIn("✅ 100% Firmowy", html_100)


if __name__ == "__main__":
    unittest.main()
