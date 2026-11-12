"""
src/web/routers/dashboard.py
Trasa główna: Pulpit Przedsiębiorcy, Paczka Przelewów i Wskaźniki.
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context

router = APIRouter(tags=["Pulpit"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def load_settlement_data(profile, rok: str, miesiac: str) -> Optional[Dict[str, Any]]:
    """Ładuje dane rozliczenia z pliku rozliczenie.json jeśli istnieje."""
    if not profile:
        return None
    settlement_file = profile.katalog_firmy / "rozliczenia" / rok / miesiac / "rozliczenie.json"
    if settlement_file.exists():
        try:
            with open(settlement_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def load_aml_stats(profile, rok: str, miesiac: str) -> Optional[Dict[str, Any]]:
    """Ładuje statystyki compliance z raportu weryfikacji."""
    if not profile:
        return None
    aml_file = profile.katalog_firmy / "weryfikacje" / rok / miesiac / "raport-weryfikacji.json"
    if aml_file.exists():
        try:
            with open(aml_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("statystyki")
        except Exception:
            return None
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    """Główny widok pulpitu przedsiębiorcy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    settlement = load_settlement_data(profile, rok, miesiac)
    aml_stats = load_aml_stats(profile, rok, miesiac)

    ctx["settlement"] = settlement
    ctx["aml_stats"] = aml_stats
    ctx["active_tab"] = "dashboard"

    return templates.TemplateResponse(request=request, name="pages/dashboard.html", context=ctx)
