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
from src.web.services.qr_generator import get_transfer_qr_package
from fastapi import HTTPException

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


@router.get("/api/settlement/qr/{typ}", response_class=HTMLResponse)
async def get_transfer_qr_modal(request: Request, typ: str):
    """Generuje modal z kodem QR płatności bankowej (ZBP) dla PIT-28, VAT-7 lub ZUS."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    settlement = load_settlement_data(profile, rok, miesiac)
    typ_norm = typ.lower()

    kwota = "0.00"
    if typ_norm in ("pit28", "pit-28", "pit"):
        typ_name = "PIT-28"
        rachunek = f"10101000550225{profile.nip}000"
        if settlement and settlement.get("pit28"):
            kwota = str(settlement["pit28"].get("zaliczka_pit28_zaokraglona", "0"))
    elif typ_norm in ("vat7", "vat-7", "vat"):
        typ_name = "VAT-7"
        rachunek = f"10101000550225{profile.nip}000"
        if settlement and settlement.get("vat"):
            kwota = str(settlement["vat"].get("vat_do_zaplaty_zaokraglony", "0"))
    elif typ_norm in ("zus", "zus-nrs"):
        typ_name = "ZUS"
        rachunek = f"8310101023000026{profile.nip}"
        if settlement and settlement.get("zus"):
            kwota = f"{float(settlement['zus'].get('lacznie_do_zaplaty', 0)):.2f}"
    else:
        raise HTTPException(status_code=400, detail=f"Nieznany typ przelewu: {typ}")

    qr_pkg = get_transfer_qr_package(
        typ=typ_name,
        rachunek=rachunek,
        kwota=kwota,
        rok=rok,
        miesiac=miesiac,
        nip=profile.nip,
        nazwa_firmy=profile.nazwa,
    )

    modal_ctx = {
        "request": request,
        "qr": qr_pkg,
    }
    return templates.TemplateResponse(request=request, name="partials/transfer_qr_modal.html", context=modal_ctx)

