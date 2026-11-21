"""
src/web/services/llm/openai_provider.py
Adapter dla OpenAI (GPT-4o, GPT-4o-mini) oraz lokalnych modeli Ollama/vLLM.
Działa w procesie Pythona (Zero-CLI) z wykorzystaniem klienta httpx.
"""
import os
import json
from typing import List, Optional, AsyncGenerator

import httpx

from src.web.services.llm.base import BaseLLMProvider, ChatMessage


class OpenAIProvider(BaseLLMProvider):
    """Adapter dla OpenAI API oraz lokalnych endpointów zgodnych z OpenAI (np. Ollama)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
    ):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._model = model
        self._base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        # Dla lokalnego Ollama klucz może być 'ollama' lub dowolny, sprawdzamy obecność klucza lub custom base_url
        return bool(self._api_key or "localhost" in self._base_url or "127.0.0.1" in self._base_url)

    def _build_payload(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str],
        temperature: float,
        stream: bool = False,
    ) -> dict:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        return {
            "model": self._model,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": stream,
        }

    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_configured():
            raise ValueError("OPENAI_API_KEY nie został skonfigurowany.")

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, system_prompt, temperature, stream=False)

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Błąd OpenAI API ({resp.status_code}): {resp.text}")

            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        if not self.is_configured():
            raise ValueError("OPENAI_API_KEY nie został skonfigurowany.")

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, system_prompt, temperature, stream=True)

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise RuntimeError(f"Błąd strumienia OpenAI ({response.status_code}): {err_body.decode('utf-8')}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                        except json.JSONDecodeError:
                            continue
