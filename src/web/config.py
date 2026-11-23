"""
src/web/config.py
Konfiguracja warstwy webowej TaxPilot AI.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

DEFAULT_HOST = os.getenv("TAXPILOT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("TAXPILOT_PORT", "8000"))
DEBUG = os.getenv("TAXPILOT_DEBUG", "True").lower() in ("true", "1", "yes")

# Opcjonalny token autoryzacyjny dla instancji sieciowych/VPN (NET-1)
TAXPILOT_ACCESS_TOKEN = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip()

COOKIE_ACTIVE_NIP = "taxpilot_active_nip"
COOKIE_ACTIVE_YEAR = "taxpilot_active_year"
COOKIE_ACTIVE_MONTH = "taxpilot_active_month"
COOKIE_AUTH_TOKEN = "taxpilot_auth_token"

DEFAULT_YEAR = "2026"
DEFAULT_MONTH = "01"


def find_agy_binary() -> Optional[str]:
    """
    Wyszukuje ścieżkę do binarza agy (Antigravity CLI) na systemach Windows, Linux i macOS.
    Obsługuje standardowe lokalizacje instalatora Windows (%LOCALAPPDATA%\\agy\\bin\\agy.exe)
    oraz Unix (~/.local/bin/agy).
    """
    # 1. Sprawdź bieżący PATH procesu
    bin_path = shutil.which("agy")
    if bin_path:
        return bin_path

    # 2. Dedykowane lokalizacje na Windows
    if os.name == "nt":
        candidates = []
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.extend(
                [
                    Path(local_appdata) / "agy" / "bin" / "agy.exe",
                    Path(local_appdata) / "agy" / "bin" / "agy.cmd",
                ]
            )
        candidates.extend(
            [
                Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
                Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.cmd",
            ]
        )
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.extend(
                [
                    Path(appdata) / "Antigravity" / "bin" / "agy.cmd",
                    Path(appdata) / "Antigravity" / "bin" / "agy.exe",
                    Path(appdata) / "Antigravity" / "bin" / "agy-node.cmd",
                ]
            )
        candidates.extend(
            [
                Path.home() / ".gemini" / "antigravity" / "bin" / "agy.exe",
                Path.home() / ".gemini" / "antigravity" / "bin" / "agy.cmd",
                Path.home() / ".gemini" / "antigravity-cli" / "bin" / "agy.exe",
            ]
        )

        # Sprawdź też PATH zapisany w rejestrze użytkownika Windows (jeśli instalator dodał go
        # w trakcie działania serwera i proces nadrzędny jeszcze nie przeładował środowiska)
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                reg_path, _ = winreg.QueryValueEx(key, "Path")
                if reg_path:
                    resolved = shutil.which("agy", path=reg_path)
                    if resolved:
                        return resolved
        except Exception:
            pass

        for cand in candidates:
            if cand.is_file() and (os.access(cand, os.X_OK) or cand.suffix.lower() in (".exe", ".cmd", ".bat")):
                return str(cand)

    # 3. Dedykowane lokalizacje na Linux / macOS
    unix_candidates = [
        Path.home() / ".local" / "bin" / "agy",
        Path.home() / ".gemini" / "antigravity" / "bin" / "agy",
        Path("/usr/local/bin/agy"),
        Path("/opt/homebrew/bin/agy"),
    ]
    for cand in unix_candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)

    return None


def get_llm_status(profile: Optional[Any] = None) -> Dict[str, Any]:
    """
    Sprawdza obecność skonfigurowanych silników LLM w profilu firmy lub środowisku (LLM-Awareness).
    Zwraca informacje o aktywnym providerze lub informuje o trybie deterministycznym (Zero-LLM).
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    forced_provider = os.getenv("TAXPILOT_LLM_PROVIDER", "").lower()
    custom_model = os.getenv("TAXPILOT_LLM_MODEL")

    # Sprawdzenie konfiguracji zapisanej w profilu firmy (profil.json)
    if profile:
        llm_cfg = getattr(profile, "llm", None) or {}
        if isinstance(llm_cfg, dict):
            if not forced_provider or forced_provider == "auto":
                forced_provider = llm_cfg.get("provider", "").lower()
            if not custom_model and llm_cfg.get("model"):
                custom_model = llm_cfg.get("model")

    agy_bin = find_agy_binary()

    # 1. Obsługa providera Antigravity (lokalny agent CLI "agy")
    if forced_provider in ("antigravity", "agy", "local", "cli"):
        model = custom_model or "antigravity-cli"
        is_avail = agy_bin is not None
        return {
            "available": is_avail,
            "provider": "antigravity",
            "model": model,
            "binary_path": agy_bin or "brak w PATH",
            "mode": "local_cli",
            "label": f"Antigravity CLI ({model})" if is_avail else "Antigravity CLI (brak binarki agy)",
        }

    # 2. Jawny wybór providera chmurowego
    if forced_provider == "gemini" and gemini_key:
        model = custom_model or "gemini-1.5-flash"
        return {
            "available": True,
            "provider": "gemini",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"Gemini ({model})",
        }
    elif forced_provider in ("claude", "anthropic") and anthropic_key:
        model = custom_model or "claude-3-5-sonnet"
        return {
            "available": True,
            "provider": "claude",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"Claude ({model})",
        }
    elif forced_provider == "openai" and openai_key:
        model = custom_model or "gpt-4o"
        return {
            "available": True,
            "provider": "openai",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"OpenAI ({model})",
        }
    elif forced_provider in ("null", "deterministic", "none"):
        return {
            "available": False,
            "provider": "none",
            "model": "deterministic",
            "mode": "deterministic",
            "label": "Deterministyczny (Zero-LLM)",
        }

    # 3. Tryb automatyczny (wg priorytetu skonfigurowanych kluczy API)
    if anthropic_key:
        model = custom_model or "claude-3-5-sonnet"
        return {
            "available": True,
            "provider": "claude",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"Claude ({model})",
        }
    elif gemini_key:
        model = custom_model or "gemini-1.5-flash"
        return {
            "available": True,
            "provider": "gemini",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"Gemini ({model})",
        }
    elif openai_key:
        model = custom_model or "gpt-4o"
        return {
            "available": True,
            "provider": "openai",
            "model": model,
            "mode": "cloud_sdk",
            "label": f"OpenAI ({model})",
        }

    return {
        "available": False,
        "provider": "none",
        "model": "deterministic",
        "mode": "deterministic",
        "label": "Deterministyczny (Zero-LLM)",
    }
