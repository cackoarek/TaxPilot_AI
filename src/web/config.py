"""
src/web/config.py
Konfiguracja warstwy webowej TaxPilot AI.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FIRMY_DIR = BASE_DIR / "firmy"
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

DEFAULT_HOST = os.getenv("TAXPILOT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("TAXPILOT_PORT", "8000"))
DEBUG = os.getenv("TAXPILOT_DEBUG", "True").lower() in ("true", "1", "yes")

COOKIE_ACTIVE_NIP = "taxpilot_active_nip"
COOKIE_ACTIVE_YEAR = "taxpilot_active_year"
COOKIE_ACTIVE_MONTH = "taxpilot_active_month"

DEFAULT_YEAR = "2026"
DEFAULT_MONTH = "01"


def get_llm_status() -> Dict[str, Any]:
    """
    Sprawdza obecność skonfigurowanych silników LLM w środowisku (LLM-Awareness).
    Zwraca informacje o aktywnym providerze lub informuje o trybie deterministycznym (Zero-LLM).
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    forced_provider = os.getenv("TAXPILOT_LLM_PROVIDER", "auto").lower()

    if forced_provider == "gemini" and gemini_key:
        return {"available": True, "provider": "gemini", "model": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"}
    elif forced_provider == "claude" and anthropic_key:
        return {"available": True, "provider": "claude", "model": "claude-3-5-sonnet", "label": "Claude 3.5 Sonnet"}
    elif forced_provider == "openai" and openai_key:
        return {"available": True, "provider": "openai", "model": "gpt-4o", "label": "GPT-4o"}

    # Tryb automatyczny (wg priorytetu dostępnych kluczy)
    if anthropic_key:
        return {"available": True, "provider": "claude", "model": "claude-3-5-sonnet", "label": "Claude 3.5 Sonnet"}
    elif gemini_key:
        return {"available": True, "provider": "gemini", "model": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"}
    elif openai_key:
        return {"available": True, "provider": "openai", "model": "gpt-4o", "label": "GPT-4o"}

    return {
        "available": False,
        "provider": "none",
        "model": "deterministic",
        "label": "Deterministyczny (Zero-LLM)"
    }
