"""
tests/test_web_copilot.py
Testy integracyjne architektury Multi-Provider LLM oraz asystenta AI Copilot (Kamień Milowy M4).
"""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.core.company import CompanyProfile
from src.web.app import app
from src.web.services.copilot_service import CopilotService
from src.web.services.llm.claude_provider import ClaudeProvider
from src.web.services.llm.factory import LLMProviderFactory
from src.web.services.llm.gemini_provider import GeminiProvider
from src.web.services.llm.null_provider import NullProvider
from src.web.services.llm.openai_provider import OpenAIProvider


class TestWebCopilot(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP

        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"

    def test_factory_returns_null_provider_when_no_keys(self):
        """Test czy fabryka domyślnie zwraca NullProvider gdy brak kluczy API."""
        with patch.dict(os.environ, {}, clear=True):
            provider = LLMProviderFactory.get_provider()
            self.assertIsInstance(provider, NullProvider)
            self.assertEqual(provider.provider_name, "null")
            self.assertFalse(provider.is_configured())

    def test_factory_returns_gemini_when_key_set(self):
        """Test wyboru GeminiProvider gdy obecny GEMINI_API_KEY."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyFakeKey123"}, clear=True):
            provider = LLMProviderFactory.get_provider()
            self.assertIsInstance(provider, GeminiProvider)
            self.assertEqual(provider.provider_name, "gemini")
            self.assertTrue(provider.is_configured())

    def test_factory_returns_claude_when_key_set(self):
        """Test wyboru ClaudeProvider gdy obecny ANTHROPIC_API_KEY."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fake-key-123"}, clear=True):
            provider = LLMProviderFactory.get_provider()
            self.assertIsInstance(provider, ClaudeProvider)
            self.assertEqual(provider.provider_name, "claude")
            self.assertTrue(provider.is_configured())

    def test_factory_returns_openai_when_key_set(self):
        """Test wyboru OpenAIProvider gdy obecny OPENAI_API_KEY."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-fake-key-123"}, clear=True):
            provider = LLMProviderFactory.get_provider()
            self.assertIsInstance(provider, OpenAIProvider)
            self.assertEqual(provider.provider_name, "openai")
            self.assertTrue(provider.is_configured())

    def test_factory_honors_override(self):
        """Test wymuszenia wyboru konkretnego providera przez override."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyFakeKey123", "ANTHROPIC_API_KEY": "sk-ant-123"}):
            # Mimo że Claude miałby priorytet, wymuszamy gemini
            provider = LLMProviderFactory.get_provider(provider_override="gemini")
            self.assertIsInstance(provider, GeminiProvider)

    def test_copilot_system_prompt_builder(self):
        """Test budowania promptu systemowego z kontekstem firmy (Zero-Hallucination)."""
        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile:
            from tests.fixtures import setup_test_company

            profile = setup_test_company()
        self.assertIsNotNone(profile)
        prompt = CopilotService.build_system_prompt(profile, "2026", "01")

        self.assertIn(profile.nazwa, prompt)
        self.assertIn(profile.nip, prompt)
        self.assertIn("Zero-Hallucination", prompt)
        self.assertIn("RYCZALT", prompt)
        self.assertIn("BEZWZGLĘDNA IZOLACJA DANYCH FIRMY", prompt)
        self.assertIn("WYŁĄCZNIE w ramach firmy", prompt)

    def test_copilot_status_endpoint(self):
        """Test endpointu GET /api/copilot/status."""
        response = self.client.get("/api/copilot/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("available", data)
        self.assertIn("provider", data)
        self.assertIn("label", data)

    def test_copilot_chat_endpoint_htmx(self):
        """Test endpointu POST /api/copilot/chat dla żądania HTMX (zwraca dymek HTML)."""
        with patch.object(LLMProviderFactory, "get_provider", return_value=NullProvider()):
            response = self.client.post(
                "/api/copilot/chat",
                data={"message": "Jak rozliczyć miesiąc?"},
            )
            self.assertEqual(response.status_code, 200)
            html = response.text
            self.assertIn("Jak rozliczyć miesiąc?", html)
            self.assertIn("prose", html)
            self.assertIn("Wstępny Przegląd Dokumentów", html)

    def test_copilot_chat_endpoint_streaming(self):
        """Test endpointu POST /api/copilot/chat?stream=true dla SSE."""
        with patch.object(LLMProviderFactory, "get_provider", return_value=NullProvider()):
            response = self.client.post(
                "/api/copilot/chat?stream=true",
                data={"message": "Składki ZUS"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/event-stream", response.headers["content-type"])
            self.assertIn("data:", response.text)
            self.assertIn("[DONE]", response.text)

    def test_copilot_chat_empty_message_returns_400(self):
        """Test pustej wiadomości."""
        response = self.client.post(
            "/api/copilot/chat",
            data={"message": "   "},
        )
        self.assertEqual(response.status_code, 400)

    def test_copilot_reset_endpoint(self):
        """Test endpointu POST /api/copilot/reset resetującego sesję AI."""
        response = self.client.post("/api/copilot/reset")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sesja AI została pomyślnie zresetowana", response.text)

    def test_markdown_to_html_table_rendering(self):
        """Weryfikuje, czy tabele Markdown są poprawnie renderowane do kodu HTML table."""
        from src.web.routers.copilot import markdown_to_html

        md = (
            "Oto zestawienie:\n\n"
            "| Pozycja | Kwota | Termin |\n"
            "|---|---|---|\n"
            "| Podatek PIT-28 | **500,00 zł** | 20. dnia |\n"
            "| VAT-7 | **200,00 zł** | 25. dnia |\n"
        )
        html = markdown_to_html(md)
        self.assertIn("<table", html)
        self.assertIn("<thead", html)
        self.assertIn("<tbody", html)
        self.assertIn("Podatek PIT-28", html)
        self.assertIn("<strong>500,00 zł</strong>", html)
        self.assertNotIn("|---|---|---|", html)

    def test_markdown_to_html_code_and_formatting(self):
        """Weryfikuje obsługę bloków kodu, nagłówków i list w markdown_to_html."""
        from src.web.routers.copilot import markdown_to_html

        md = "### Tytuł sekcji\n\n- Punkt pierwszy\n- Punkt drugi\n\n```python\nprint('hello')\n```\n"
        html = markdown_to_html(md)
        self.assertIn("<h4", html)
        self.assertIn("Tytuł sekcji", html)
        self.assertIn("<ul", html)
        self.assertIn("<li", html)
        self.assertIn("<pre", html)
        self.assertIn("print('hello')", html)

    def test_message_status_endpoint_pending_and_done(self):
        """Test endpointu GET /api/copilot/message-status dla statusu pending oraz done."""
        from src.web.routers.copilot import CopilotSessionHistory

        session_id = "company_7770001122"
        record = CopilotSessionHistory.add_message(session_id, "Testowe pytanie?")

        # 1. Sprawdzenie stanu pending (powinien zwracać polling na samego siebie bez migania całego kontenera)
        res_pending = self.client.get(f"/api/copilot/message-status?id={record.id}")
        self.assertEqual(res_pending.status_code, 200)
        self.assertIn('hx-trigger="every 1s"', res_pending.text)
        self.assertIn('hx-target="this"', res_pending.text)
        self.assertIn("Asystent AI analizuje dane", res_pending.text)

        # 2. Aktualizacja do statusu done
        CopilotSessionHistory.update_message(session_id, record.id, "<p>Gotowa odpowiedź asystenta</p>", status="done")
        res_done = self.client.get(f"/api/copilot/message-status?id={record.id}")
        self.assertEqual(res_done.status_code, 200)
        self.assertNotIn("hx-trigger", res_done.text)
        self.assertIn("Gotowa odpowiedź asystenta", res_done.text)
        self.assertIn("prose", res_done.text)

    def test_copilot_history_no_container_flickering(self):
        """Test weryfikujący, że historia czatu nie narzuca globalnego przeładowania całego kontenera."""
        from unittest.mock import MagicMock

        from src.web.dependencies import get_global_context
        from src.web.routers.copilot import CopilotSessionHistory

        ctx = get_global_context(MagicMock(query_params={}, cookies=self.client.cookies))
        profile = ctx.get("profile")
        nip = profile.nip if profile else "default"
        session_id = f"company_{nip}"
        CopilotSessionHistory.clear(session_id)
        CopilotSessionHistory.add_message(session_id, "Pytanie 1")

        res = self.client.get("/api/copilot/history")
        self.assertEqual(res.status_code, 200)
        # Nie powinno być container-level innerHTML wipe ani every 1.5s
        self.assertNotIn('hx-swap="innerHTML"', res.text)
        self.assertNotIn("every 1.5s", res.text)

    def test_chat_sessions_manager_crud(self):
        """Test operacji CRUD na trwałych sesjach czatu w ChatSessionManager."""
        from src.web.services.chat_session_service import ChatSessionManager

        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile:
            from tests.fixtures import setup_test_company

            profile = setup_test_company()
        self.assertIsNotNone(profile)

        # 1. Tworzenie nowej sesji z domyślnym tytułem
        session = ChatSessionManager.create_new_session(profile, "2026", "10", title="Nowa rozmowa")
        self.assertIsNotNone(session.id)
        self.assertEqual(session.title, "Nowa rozmowa")

        # 2. Dodawanie pytań i automatyczna aktualizacja tytułu
        session.add_user_message("Jakie mam koszty paliwa w październiku?")
        self.assertIn("Jakie mam koszty", session.title)
        ChatSessionManager.save_session(profile, session)

        # 3. Weryfikacja odczytu z dysku
        loaded = ChatSessionManager.load_session(profile, session.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.messages), 1)
        self.assertEqual(loaded.messages[0].user_message, "Jakie mam koszty paliwa w październiku?")

        # 4. Zmiana nazwy sesji
        renamed = ChatSessionManager.rename_session(profile, session.id, "Koszty Paliwa 2026-10")
        self.assertTrue(renamed)
        loaded_renamed = ChatSessionManager.load_session(profile, session.id)
        self.assertEqual(loaded_renamed.title, "Koszty Paliwa 2026-10")

        # 5. Lista sesji zawiera nowo utworzoną
        sessions = ChatSessionManager.list_sessions(profile)
        ids = [s["id"] for s in sessions]
        self.assertIn(session.id, ids)

        # 6. Usunięcie sesji
        deleted = ChatSessionManager.delete_session(profile, session.id)
        self.assertTrue(deleted)
        self.assertIsNone(ChatSessionManager.load_session(profile, session.id))

    def test_copilot_sessions_api_endpoints(self):
        """Test endpointów HTTP zarządzania sesjami czatu (/api/copilot/sessions)."""
        # 1. Tworzenie nowej sesji przez POST /api/copilot/sessions/new
        res_new = self.client.post("/api/copilot/sessions/new")
        self.assertEqual(res_new.status_code, 200)
        self.assertIn("Nowy wątek rozmowy", res_new.text)
        self.assertIn("copilot-active-session-title-container", res_new.text)

        # 2. Pobranie listy sesji przez GET /api/copilot/sessions
        res_list = self.client.get("/api/copilot/sessions")
        self.assertEqual(res_list.status_code, 200)
        self.assertIn("Aktywna", res_list.text)

        # 3. Pobranie tytułu aktywnej sesji przez GET /api/copilot/active-title
        res_title = self.client.get("/api/copilot/active-title")
        self.assertEqual(res_title.status_code, 200)
        self.assertIn("copilot-session-title", res_title.text)

        # 4. Zmiana nazwy sesji przez POST /api/copilot/session-rename
        from src.web.services.chat_session_service import ChatSessionManager

        profile = CompanyProfile.load_by_nip("7770001122")
        if not profile:
            from tests.fixtures import setup_test_company

            profile = setup_test_company()
        active_sess = ChatSessionManager.get_active_session(profile)
        self.assertIsNotNone(active_sess)

        res_rename = self.client.post(
            "/api/copilot/session-rename", data={"session_id": active_sess.id, "title": "Moja Ważna Rozmowa Podatkowa"}
        )
        self.assertEqual(res_rename.status_code, 200)
        self.assertIn("Moja Ważna Rozmowa Podatkowa", res_rename.text)

        # 5. Wybór sesji przez POST /api/copilot/sessions/{session_id}/select
        res_select = self.client.post(f"/api/copilot/sessions/{active_sess.id}/select")
        self.assertEqual(res_select.status_code, 200)
        self.assertIn("Moja Ważna Rozmowa Podatkowa", res_select.text)

        # 6. Usunięcie sesji przez DELETE /api/copilot/sessions/{session_id}
        res_del = self.client.delete(f"/api/copilot/sessions/{active_sess.id}")
        self.assertEqual(res_del.status_code, 200)


if __name__ == "__main__":
    unittest.main()
