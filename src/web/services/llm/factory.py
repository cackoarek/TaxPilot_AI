"""
src/web/services/llm/factory.py
Fabryka dostawców LLM (LLMProviderFactory).
Wybiera odpowiedniego providera zgodnie z konfiguracją firmy,
zmiennymi środowiskowymi oraz dostępnymi kluczami API.
"""
import os
from typing import Optional, Dict, Any

from src.core.company import CompanyProfile
from src.web.services.llm.base import BaseLLMProvider
from src.web.services.llm.null_provider import NullProvider
from src.web.services.llm.gemini_provider import GeminiProvider
from src.web.services.llm.openai_provider import OpenAIProvider
from src.web.services.llm.claude_provider import ClaudeProvider


class LLMProviderFactory:
    """Fabryka instancji BaseLLMProvider."""

    @classmethod
    def get_provider(
        cls,
        profile: Optional[CompanyProfile] = None,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
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

        # Sprawdzenie konfiguracji z profilu firmy
        if not target_provider and profile:
            profile_data = getattr(profile, "raw_data", None)
            if not profile_data and hasattr(profile, "to_dict"):
                profile_data = profile.to_dict()
            if isinstance(profile_data, dict):
                llm_cfg = profile_data.get("llm", {})
                target_provider = llm_cfg.get("provider", "").lower()
                if not target_model:
                    target_model = llm_cfg.get("model")

        # Sprawdzenie zmiennej środowiskowej
        if not target_provider:
            target_provider = os.getenv("TAXPILOT_LLM_PROVIDER", "auto").lower()

        # Dostępne klucze API w środowisku
        gemini_key = os.getenv("GEMINI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")

        # Jawny wybór providera
        if target_provider == "gemini":
            return GeminiProvider(api_key=gemini_key, model=target_model or "gemini-2.5-flash")
        elif target_provider in ("claude", "anthropic"):
            return ClaudeProvider(api_key=anthropic_key, model=target_model or "claude-3-5-sonnet-20241022")
        elif target_provider == "openai":
            return OpenAIProvider(api_key=openai_key, model=target_model or "gpt-4o")
        elif target_provider in ("null", "deterministic", "none"):
            return NullProvider()

        # Tryb "auto": Wybór pierwszego skonfigurowanego klucza
        if anthropic_key:
            return ClaudeProvider(api_key=anthropic_key, model=target_model or "claude-3-5-sonnet-20241022")
        elif gemini_key:
            return GeminiProvider(api_key=gemini_key, model=target_model or "gemini-2.5-flash")
        elif openai_key:
            return OpenAIProvider(api_key=openai_key, model=target_model or "gpt-4o")

        # Fallback na NullProvider
        return NullProvider()
