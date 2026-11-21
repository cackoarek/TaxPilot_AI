"""
tests/test_antigravity_provider.py
Testy jednostkowe providera Antigravity (agy CLI) oraz zarządcy sesji.
"""
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

from src.web.services.llm.base import ChatMessage
from src.web.services.llm.antigravity_provider import (
    AntigravityProvider,
    AntigravitySession,
    AntigravitySessionManager,
    SYSTEM_AGENTS_INSTRUCTION,
)


class TestAntigravityProvider(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        AntigravitySessionManager.reset_session("test_session")

    def test_session_initialization_includes_agents_md(self):
        """Weryfikuje, czy pierwsza tura sesji wymusza zapoznanie się z AGENTS.md."""
        session = AntigravitySession(session_id="test_init")
        self.assertFalse(session.initialized)

        prompt1 = session.build_turn_prompt("Dzień dobry, ile mam ZUS do zapłaty?")
        self.assertTrue(session.initialized)
        self.assertIn("AGENTS.md", prompt1)
        self.assertIn("BEZWZGLĘDNA IZOLACJA DANYCH FIRMY", prompt1)
        self.assertIn("Dzień dobry, ile mam ZUS do zapłaty?", prompt1)

        # Druga tura nie powinna powielać instrukcji startowej
        prompt2 = session.build_turn_prompt("A ile podatku PIT-28?")
        self.assertNotIn("INSTRUKCJA STARTOWA", prompt2)
        self.assertEqual(prompt2, "A ile podatku PIT-28?")

    @patch("shutil.which")
    def test_is_configured(self, mock_which):
        mock_which.return_value = "/usr/local/bin/agy"
        provider = AntigravityProvider(binary_path="agy")
        self.assertTrue(provider.is_configured())

        mock_which.return_value = None
        provider_missing = AntigravityProvider(binary_path="/nieistniejaca/sciezka/agy_brak")
        self.assertFalse(provider_missing.is_configured())

    @patch("asyncio.create_subprocess_exec")
    @patch("shutil.which")
    async def test_chat_async_two_turns_maintains_session(self, mock_which, mock_exec):
        mock_which.return_value = "/usr/local/bin/agy"

        # Mock procesu 1
        proc1 = AsyncMock()
        proc1.communicate.return_value = (b"Odpowiedz 1 od agy", b"")
        proc1.returncode = 0

        # Mock procesu 2
        proc2 = AsyncMock()
        proc2.communicate.return_value = (b"Odpowiedz 2 kontynuacja", b"")
        proc2.returncode = 0

        mock_exec.side_effect = [proc1, proc2]

        provider = AntigravityProvider(session_id="test_session")

        # Tura 1
        res1 = await provider.chat_async([ChatMessage(role="user", content="Rozlicz październik")])
        self.assertEqual(res1, "Odpowiedz 1 od agy")

        # Sprawdzenie argumentów pierwszego wywołania
        args1, _ = mock_exec.call_args_list[0]
        self.assertIn("-p", args1)
        self.assertNotIn("--continue", args1)

        # Tura 2 - powinna zawierać flagę --continue
        res2 = await provider.chat_async([ChatMessage(role="user", content="Wygeneruj przelewy")])
        self.assertEqual(res2, "Odpowiedz 2 kontynuacja")

        args2, _ = mock_exec.call_args_list[1]
        self.assertIn("--continue", args2)

    def test_session_per_company_isolation(self):
        """Weryfikuje, czy każda firma posiada niezależną sesję."""
        AntigravitySessionManager.reset_all()

        profile_a = {"nip": "1111111111", "nazwa": "Firma Alpha"}
        profile_b = {"nip": "2222222222", "nazwa": "Firma Beta"}

        session_a = AntigravitySessionManager.get_or_create_session(
            session_id="company_1111111111",
            profile=profile_a,
            rok="2026",
            miesiac="10",
        )
        session_b = AntigravitySessionManager.get_or_create_session(
            session_id="company_2222222222",
            profile=profile_b,
            rok="2026",
            miesiac="11",
        )

        self.assertNotEqual(session_a, session_b)
        self.assertEqual(session_a.company_nip, "1111111111")
        self.assertEqual(session_b.company_nip, "2222222222")

    def test_context_activation_includes_company_and_period(self):
        """Weryfikuje, czy inicjalizacja kontekstu przekazuje agentowi aktywną firmę i wybrany okres."""
        profile = {
            "nip": "7770001122",
            "nazwa": "CloudTech Solutions",
            "platnik_vat": True,
        }
        session = AntigravitySession(
            session_id="company_7770001122",
            profile=profile,
            rok="2026",
            miesiac="10",
        )
        prompt = session.build_turn_prompt("Podsumuj przychody")

        self.assertIn("AGENTS.md", prompt)
        self.assertIn("CloudTech Solutions", prompt)
        self.assertIn("7770001122", prompt)
        self.assertIn("2026-10", prompt)
        self.assertIn("stronie WWW", prompt)
        self.assertIn("TABELE", prompt)
        self.assertIn("Podsumuj przychody", prompt)

    def test_period_switch_informs_agent(self):
        """Weryfikuje, czy zmiana okresu w trwającej sesji generuje powiadomienie o nowym okresie."""
        session = AntigravitySession(
            session_id="company_test",
            company_nip="1234567890",
            rok="2026",
            miesiac="10",
        )
        # Tura 1: inicjacja
        prompt1 = session.build_turn_prompt("Pytanie 1", rok="2026", miesiac="10")
        self.assertIn("2026-10", prompt1)

        # Tura 2: ten sam okres -> brak notatki o zmianie okresu
        prompt2 = session.build_turn_prompt("Pytanie 2", rok="2026", miesiac="10")
        self.assertNotIn("ZMIANA WYBRANEGO OKRESU", prompt2)

        # Tura 3: użytkownik przełączył okres na 2026-11
        prompt3 = session.build_turn_prompt("Pytanie 3", rok="2026", miesiac="11")
        self.assertIn("[ZMIANA WYBRANEGO OKRESU ROZLICZENIOWEGO]", prompt3)
        self.assertIn("2026-11", prompt3)

    @patch("shutil.which")
    @patch("asyncio.create_subprocess_exec")
    async def test_stream_chat_emits_lines_and_records_last_output(self, mock_exec, mock_which):
        """Weryfikuje, że stream_chat czyta linie w czasie rzeczywistym i aktualizuje last_output."""
        mock_which.return_value = "/usr/local/bin/agy"

        proc = AsyncMock()
        proc.stdout.readline = AsyncMock(side_effect=[
            b"Linia 1 od agenta\n",
            b"Linia 2 od agenta\n",
            b""
        ])
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_exec.return_value = proc

        provider = AntigravityProvider(session_id="stream_test_session")
        chunks = []
        async for chunk in provider.stream_chat([ChatMessage(role="user", content="Pytanie")]):
            chunks.append(chunk)

        self.assertEqual(chunks, ["Linia 1 od agenta\n", "Linia 2 od agenta\n"])
        session = AntigravitySessionManager.get_or_create_session("stream_test_session")
        self.assertIn("Linia 1", session.last_output)
        self.assertIn("Linia 2", session.last_output)

    def test_session_reset_terminates_running_process(self):
        """Weryfikuje, że reset sesji przerywa proces w tle."""
        session = AntigravitySessionManager.get_or_create_session("proc_test_session")
        mock_proc = MagicMock()
        mock_proc.returncode = None
        session.current_process = mock_proc

        AntigravitySessionManager.reset_session("proc_test_session")
        mock_proc.terminate.assert_called_once()
        self.assertNotIn("proc_test_session", AntigravitySessionManager._instances)


if __name__ == "__main__":
    unittest.main()
