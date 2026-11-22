"""
src/web/services/llm/factory.py
Fabryka dostawców LLM (LLMProviderFactory).
Wybiera odpowiedniego providera zgodnie z konfiguracją firmy,
zmiennymi środowiskowymi oraz dostępnymi kluczami API.
"""

import os
from typing import Optional

from src.core.company import CompanyProfile
from src.logging_config import get_logger
from src.web.services.llm.antigravity_provider import AntigravityProvider
from src.web.services.llm.base import BaseLLMProvider
from src.web.services.llm.claude_provider import ClaudeProvider
from src.web.services.llm.gemini_provider import GeminiProvider
from src.web.services.llm.null_provider import NullProvider
from src.web.services.llm.openai_provider import OpenAIProvider

logger = get_logger("taxpilot.llm.factory")


class LLMProviderFactory:
    """Fabryka instancji BaseLLMProvider."""

    @classmethod
    def get_provider(
        cls,
        profile: Optional[CompanyProfile] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        session_id: Optional[str] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
    ) -> BaseLLMProvider:
        """
        Zwraca instancję skonfigurowanego dostawcy LLM.
        Hierarchia wyboru:
        1. provider_override (jeśli podany wprost w wywołaniu)
        2. Ustawienia profilu firmy (jeśli istnieją w profil.json w sekcji 'llm')
        3. Zmienna TAXPILOT_LLM_PROVIDER
        4. Automatyczna detekcja wg obecności kluczy API:
           - ANTHROPIC_API_KEY -> ClaudeProvider
           - GEMINI_API_KEY -> GeminiProvider
           - OPENAI_API_KEY -> OpenAIProvider
        5. Fallback na NullProvider (deterministyczny tryb Zero-LLM)
        """
        target_provider = (provider_override or "").lower()
        target_model = model_override

        # Domyślny session_id przypisany per wybrana firma
        if not session_id:
            nip = getattr(profile, "nip", None) or (profile.get("nip") if isinstance(profile, dict) else None)
            session_id = f"company_{nip}" if nip else "default"

        # Sprawdzenie konfiguracji z profilu firmy
        if profile:
            llm_cfg = {}
            if getattr(profile, "llm", None):
                llm_cfg = profile.llm
            elif hasattr(profile, "to_dict"):
                llm_cfg = profile.to_dict().get("llm", {})

            if isinstance(llm_cfg, dict):
                if not target_provider:
                    target_provider = llm_cfg.get("provider", "").lower()
                if not target_model and llm_cfg.get("model"):
                    target_model = llm_cfg.get("model")

        # Sprawdzenie zmiennej środowiskowej
        if not target_provider or target_provider == "auto":
            target_provider = os.getenv("TAXPILOT_LLM_PROVIDER", "auto").lower()

        if not target_model:
            target_model = os.getenv("TAXPILOT_LLM_MODEL")

        # Dostępne klucze API w środowisku
        gemini_key = os.getenv("GEMINI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        provider: BaseLLMProvider
        # Jawny wybór providera
        if target_provider in ("antigravity", "agy", "local", "cli"):
            provider = AntigravityProvider(
                model=target_model or "antigravity-cli",
                session_id=session_id,
                profile=profile,
                rok=rok,
                miesiac=miesiac,
            )
        elif target_provider == "gemini":
            provider = GeminiProvider(api_key=gemini_key, model=target_model or "gemini-1.5-flash")
        elif target_provider in ("claude", "anthropic"):
            provider = ClaudeProvider(api_key=anthropic_key, model=target_model or "claude-3-5-sonnet-20241022")
        elif target_provider == "openai":
            provider = OpenAIProvider(api_key=openai_key, model=target_model or "gpt-4o")
        elif target_provider in ("null", "deterministic", "none"):
            provider = NullProvider()
        # Tryb "auto": Wybór pierwszego skonfigurowanego klucza API
        elif anthropic_key:
            provider = ClaudeProvider(api_key=anthropic_key, model=target_model or "claude-3-5-sonnet-20241022")
        elif gemini_key:
            provider = GeminiProvider(api_key=gemini_key, model=target_model or "gemini-1.5-flash")
        elif openai_key:
            provider = OpenAIProvider(api_key=openai_key, model=target_model or "gpt-4o")
        else:
            provider = NullProvider()

        logger.info(
            "Wybrano providera LLM: %s, model: %s (skonfigurowany=%s)",
            provider.provider_name,
            getattr(provider, "model_name", "brak"),
            provider.is_configured(),
        )
        return provider
