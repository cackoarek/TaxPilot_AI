"""
src/web/services/llm/gemini_provider.py
Adapter dla modeli Google Gemini (np. gemini-2.5-flash, gemini-1.5-pro).
Działa w procesie Pythona (Zero-CLI) z wykorzystaniem asynchronicznego klienta HTTP httpx.
"""
import os
import json
from typing import List, Optional, AsyncGenerator

import httpx

from src.web.services.llm.base import BaseLLMProvider, ChatMessage


class GeminiProvider(BaseLLMProvider):
    """Adapter dla Google Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model
        self._base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key and len(self._api_key.strip()) > 5)

    def _build_payload(self, messages: List[ChatMessage], system_prompt: Optional[str], temperature: float) -> dict:
        contents = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}]
            })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            }
        }
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }
        return payload

    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_configured():
            raise ValueError("GEMINI_API_KEY nie został skonfigurowany.")

        url = f"{self._base_url}/{self._model}:generateContent?key={self._api_key}"
        payload = self._build_payload(messages, system_prompt, temperature)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Błąd Gemini API ({resp.status_code}): {resp.text}")

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        if not self.is_configured():
            raise ValueError("GEMINI_API_KEY nie został skonfigurowany.")

        url = f"{self._base_url}/{self._model}:streamGenerateContent?alt=sse&key={self._api_key}"
        payload = self._build_payload(messages, system_prompt, temperature)

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise RuntimeError(f"Błąd strumienia Gemini ({response.status_code}): {err_body.decode('utf-8')}")

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if not data_str:
                            continue
                        try:
                            chunk = json.loads(data_str)
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                text = "".join(p.get("text", "") for p in parts)
                                if text:
                                    yield text
                        except json.JSONDecodeError:
                            continue
