"""
src/version.py
Moduł zarządzania wersją aplikacji TaxPilot AI.
Wersja jest zarządzana deterministycznie: aktualizowana przez GitHub Actions przy wydawaniu tagu
oraz odczytywana z pliku VERSION, zmiennych środowiskowych lub metadanych pakietu (bez wywołań subprocess/git).
"""
import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
DEFAULT_VERSION = "0.1.0"

_CACHED_VERSION: Optional[str] = None


def get_version(cached: bool = True) -> str:
    """
    Zwraca aktualną wersję aplikacji wg priorytetu:
    1. Zmienna środowiskowa APP_VERSION lub TAXPILOT_VERSION (np. w kontenerze Docker/CI)
    2. Plik VERSION w katalogu głównym projektu (zarządzany automatycznie przez GitHub Actions)
    3. Metadane pakietu taxpilot-ai (importlib.metadata)
    4. Wersja domyślna (0.1.0)
    """
    global _CACHED_VERSION
    if cached and _CACHED_VERSION is not None:
        return _CACHED_VERSION

    # 1. Zmienna środowiskowa
    env_ver = os.getenv("APP_VERSION") or os.getenv("TAXPILOT_VERSION")
    if env_ver and env_ver.strip():
        ver = env_ver.strip()
        if cached:
            _CACHED_VERSION = ver
        return ver

    # 2. Plik VERSION
    if VERSION_FILE.exists():
        try:
            content = VERSION_FILE.read_text(encoding="utf-8").strip()
            if content:
                if cached:
                    _CACHED_VERSION = content
                return content
        except Exception:
            pass

    # 3. Metadane pakietu
    try:
        from importlib.metadata import version as pkg_version
        ver = pkg_version("taxpilot-ai")
        if ver and ver.strip():
            if cached:
                _CACHED_VERSION = ver.strip()
            return ver.strip()
    except Exception:
        pass

    # 4. Fallback domyślny
    ver = DEFAULT_VERSION
    if cached:
        _CACHED_VERSION = ver
    return ver


def get_display_version(cached: bool = True) -> str:
    """
    Zwraca wersję sformatowaną do prezentacji w interfejsie (zawsze z prefiksem 'v').
    np. 'v1.0.0', 'v0.1.0'.
    """
    ver = get_version(cached=cached)
    if not ver.startswith("v"):
        return f"v{ver}"
    return ver


def clear_version_cache() -> None:
    """Czyści podręczną pamięć wersji (przydatne np. w testach)."""
    global _CACHED_VERSION
    _CACHED_VERSION = None


__version__ = get_version(cached=False)
