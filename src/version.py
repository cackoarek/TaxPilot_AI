"""
src/version.py
Moduł zarządzania wersją aplikacji TaxPilot AI.
Obsługuje dynamiczne wykrywanie wersji z tagów git, zmiennych środowiskowych oraz plików wersji.
"""
import os
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"
DEFAULT_DEV_VERSION = "0.1.0-dev"

_CACHED_VERSION: Optional[str] = None


def _get_version_from_git() -> Optional[str]:
    """
    Pobiera wersję bezpośrednio z tagu w repozytorium git (jeśli repozytorium i tag istnieją).
    """
    try:
        git_dir = BASE_DIR / ".git"
        if not git_dir.exists():
            return None

        # 1. Próba pobrania taga przez git describe --tags
        res = subprocess.run(
            ["git", "describe", "--tags"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _get_git_commit_short() -> Optional[str]:
    """Pobiera krótki skrót bieżącego commita git."""
    try:
        git_dir = BASE_DIR / ".git"
        if not git_dir.exists():
            return None

        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def get_version(cached: bool = True) -> str:
    """
    Zwraca aktualną wersję aplikacji wg priorytetu:
    1. Zmienna środowiskowa APP_VERSION lub TAXPILOT_VERSION (np. w kontenerze/CI)
    2. Git tag (git describe --tags)
    3. Plik VERSION w katalogu głównym projektu
    4. Wersja deweloperska z hashem commita (jeśli w git)
    5. Wersja domyślna (0.1.0-dev)
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

    # 2. Git tag
    git_ver = _get_version_from_git()
    if git_ver:
        if cached:
            _CACHED_VERSION = git_ver
        return git_ver

    # 3. Plik VERSION
    if VERSION_FILE.exists():
        try:
            content = VERSION_FILE.read_text(encoding="utf-8").strip()
            if content:
                if cached:
                    _CACHED_VERSION = content
                return content
        except Exception:
            pass

    # 4. Hash commita git
    commit_short = _get_git_commit_short()
    if commit_short:
        ver = f"{DEFAULT_DEV_VERSION}+{commit_short}"
        if cached:
            _CACHED_VERSION = ver
        return ver

    # 5. Domyślny fallback
    ver = DEFAULT_DEV_VERSION
    if cached:
        _CACHED_VERSION = ver
    return ver


def get_display_version(cached: bool = True) -> str:
    """
    Zwraca wersję sformatowaną do prezentacji w interfejsie (zawsze z prefiksem 'v').
    np. 'v1.0.0', 'v0.1.0-dev'.
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
