"""
src/web/services/llm/base.py
Wspólny, ujednolicony interfejs bazowy dla dostawców LLM (Multi-Provider Pattern).
Wspiera Google Gemini, OpenAI (ChatGPT / Ollama) oraz Anthropic Claude,
oraz deterministyczny NullProvider dla trybu Zero-LLM.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional


@dataclass
class ChatMessage:
    role: str  # "user", "assistant", "system"
    content: str


@dataclass
class StreamChunk:
    text_delta: str = ""
    finish_reason: Optional[str] = None


class BaseLLMProvider(ABC):
    """Abstrakcyjna klasa bazowa dla dostawców modeli LLM."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identyfikator providera: gemini | openai | claude | null."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nazwa aktywnego modelu."""
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Czy dostawca ma poprawnie skonfigurowane klucze / endpoint."""
        pass

    @abstractmethod
    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """Asynchroniczne wywołanie modelu zwracające pełną odpowiedź."""
        pass

    @abstractmethod
    def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        """Asynchroniczny generator strumieniujący tokeny (SSE / Typewriter)."""
        pass
