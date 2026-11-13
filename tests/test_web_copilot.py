"""
tests/test_web_copilot.py
Testy integracyjne architektury Multi-Provider LLM oraz asystenta AI Copilot (Kamień Milowy M4).
"""
import unittest
import os
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import app
from src.core.company import CompanyProfile
from src.web.services.llm.base import ChatMessage
from src.web.services.llm.null_provider import NullProvider
from src.web.services.llm.gemini_provider import GeminiProvider
from src.web.services.llm.openai_provider import OpenAIProvider
from src.web.services.llm.claude_provider import ClaudeProvider
from src.web.services.llm.factory import LLMProviderFactory
from src.web.services.copilot_service import CopilotService


class TestWebCopilot(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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
        profile = CompanyProfile.load_by_nip("5322030067")
        self.assertIsNotNone(profile)
        prompt = CopilotService.build_system_prompt(profile, "2026", "01")
        
        self.assertIn(profile.nazwa, prompt)
        self.assertIn(profile.nip, prompt)
        self.assertIn("Zero-Hallucination", prompt)
        self.assertIn("RYCZALT", prompt)

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


if __name__ == "__main__":
    unittest.main()
