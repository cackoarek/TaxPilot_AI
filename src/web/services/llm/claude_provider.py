"""
src/web/services/llm/claude_provider.py
Adapter dla modeli Anthropic Claude (Claude 3.5 Sonnet, Claude 3.5 Haiku).
Działa w procesie Pythona (Zero-CLI) z wykorzystaniem klienta httpx.
"""

import json
import os
from typing import AsyncGenerator, List, Optional

import httpx

from src.web.services.llm.base import BaseLLMProvider, ChatMessage


class ClaudeProvider(BaseLLMProvider):
    """Adapter dla Anthropic Claude API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._model = model
        self._base_url = "https://api.anthropic.com/v1/messages"

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key and len(self._api_key.strip()) > 5)

    def _build_payload(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str],
        temperature: float,
        stream: bool = False,
    ) -> dict:
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": formatted_messages,
            "temperature": temperature,
            "stream": stream,
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_configured():
            raise ValueError("ANTHROPIC_API_KEY nie został skonfigurowany.")

        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, system_prompt, temperature, stream=False)

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(self._base_url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Błąd Anthropic API ({resp.status_code}): {resp.text}")

            data = resp.json()
            content_blocks = data.get("content", [])
            return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        if not self.is_configured():
            raise ValueError("ANTHROPIC_API_KEY nie został skonfigurowany.")

        headers = {
            "x-api-key": self._api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(messages, system_prompt, temperature, stream=True)

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", self._base_url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise RuntimeError(f"Błąd strumienia Claude ({response.status_code}): {err_body.decode('utf-8')}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        try:
                            event_data = json.loads(data_str)
                            event_type = event_data.get("type")
                            if event_type == "content_block_delta":
                                delta = event_data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                        except json.JSONDecodeError:
                            continue
