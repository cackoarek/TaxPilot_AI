"""
src/web/dependencies.py
Wstrzykiwanie zależności dla tras FastAPI (aktywna firma, okres, kontekst).
"""
from typing import List, Optional, Tuple
from fastapi import Request
from src.core.company import CompanyProfile
from src.config import FIRMY_DIR
from src.web.config import (
    COOKIE_ACTIVE_NIP,
    COOKIE_ACTIVE_YEAR,
    COOKIE_ACTIVE_MONTH,
    DEFAULT_YEAR,
    DEFAULT_MONTH,
    get_llm_status,
)


def get_all_companies() -> List[CompanyProfile]:
    """Zwraca listę wszystkich zarejestrowanych firm w katalogu firmy/."""
    companies = []
    if not FIRMY_DIR.exists():
        return companies
    for path in sorted(FIRMY_DIR.iterdir()):
        if path.is_dir() and not path.name.startswith("."):
            profil_path = path / "profil.json"
            if profil_path.exists():
                try:
                    profile = CompanyProfile.load_from_dir(path)
                    companies.append(profile)
                except Exception:
                    pass
    return companies


def get_active_profile(request: Request) -> Optional[CompanyProfile]:
    """
    Pobiera aktywny profil firmy na podstawie ciasteczka lub parametru query ?nip=...
    W przypadku braku, zwraca pierwszą dostępną firmę.
    """
    nip = request.query_params.get("nip") or request.cookies.get(COOKIE_ACTIVE_NIP)
    if nip:
        profile = CompanyProfile.load_by_nip(nip)
        if profile:
            return profile

    all_companies = get_all_companies()
    if all_companies:
        return all_companies[0]
    return None


def get_active_period(request: Request) -> Tuple[str, str]:
    """
    Pobiera aktywny rok i miesiąc z query params lub ciasteczek (domyślnie 2026-01).
    """
    rok = request.query_params.get("rok") or request.cookies.get(COOKIE_ACTIVE_YEAR) or DEFAULT_YEAR
    miesiac = request.query_params.get("miesiac") or request.cookies.get(COOKIE_ACTIVE_MONTH) or DEFAULT_MONTH
    # Upewnienie się że miesiąc ma 2 cyfry
    if len(miesiac) == 1:
        miesiac = f"0{miesiac}"
    return rok, miesiac


def get_global_context(request: Request) -> dict:
    """
    Zwraca globalny kontekst przekazywany do szablonów Jinja2.
    """
    profile = get_active_profile(request)
    all_companies = get_all_companies()
    rok, miesiac = get_active_period(request)
    llm_status = get_llm_status()

    return {
        "request": request,
        "profile": profile,
        "all_companies": all_companies,
        "rok": rok,
        "miesiac": miesiac,
        "llm": llm_status,
        "llm_available": llm_status["available"],
    }
