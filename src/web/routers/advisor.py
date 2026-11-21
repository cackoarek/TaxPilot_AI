"""
src/web/routers/advisor.py
Kontroler Doradcy Podatkowego: symulacja form opodatkowania (Ryczałt vs Liniowy vs Skala)
oraz audyt brakujących powtarzalnych kosztów (Expense Leak Audit).
"""
from decimal import Decimal
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context
from src.skills.tax_advisor_tools import (
    simulate_tax_regimes,
    audit_expense_leaks,
    get_annual_financial_summary,
    TaxRegimeComparison,
    ExpenseAuditResult,
)
from src.web.routers.dashboard import load_settlement_data

router = APIRouter(tags=["Doradca Podatkowy"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def clean_decimal(val: Any, default: str = "0.00") -> Decimal:
    """Konwertuje ciąg na bezpieczny Decimal."""
    try:
        s = str(val).replace(" ", "").replace(",", ".")
        return Decimal(s)
    except Exception:
        return Decimal(default)


@router.get("/doradca", response_class=HTMLResponse)
async def advisor_dashboard(
    request: Request,
    symuluj: Optional[str] = Query(None),
):
    """Główny widok Doradcy Podatkowego."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    # Pobierz deterministyczne podsumowanie za cały rok podatkowy (lub poprzedni rok w razie stycznia/braku danych)
    annual_summary = get_annual_financial_summary(profile, rok, miesiac)

    czy_symuluj_pelny = (symuluj in ["1", "true", "True"])
    if czy_symuluj_pelny and annual_summary["can_extrapolate"]:
        roczny_przychod = annual_summary["extrapolated_przychod"]
        roczny_koszt = annual_summary["extrapolated_koszt"]
    else:
        roczny_przychod = annual_summary["actual_przychod"]
        roczny_koszt = annual_summary["actual_koszt"]

    stawka_ryczaltu = Decimal(str(profile.domyslna_stawka_ryczaltu if profile else "0.12"))

    # Deterministyczna kalkulacja 3 form opodatkowania
    comparison = simulate_tax_regimes(
        przychody_roczne=roczny_przychod,
        koszty_roczne=roczny_koszt,
        stawka_ryczaltu=stawka_ryczaltu,
        rok=rok,
    )

    # Audyt powtarzalnych kosztów
    expense_audit: Optional[ExpenseAuditResult] = None
    if profile:
        expense_audit = audit_expense_leaks(profile, rok, miesiac)

    ctx["comparison"] = comparison
    ctx["expense_audit"] = expense_audit
    ctx["przychod"] = roczny_przychod
    ctx["koszt"] = roczny_koszt
    ctx["stawka_ryczaltu"] = stawka_ryczaltu
    ctx["annual_summary"] = annual_summary
    ctx["is_extrapolated"] = czy_symuluj_pelny
    ctx["active_tab"] = "advisor"

    return templates.TemplateResponse(request=request, name="pages/advisor.html", context=ctx)


@router.post("/api/advisor/simulate", response_class=HTMLResponse)
async def simulate_regimes_endpoint(
    request: Request,
    przychod: str = Form(...),
    koszt: str = Form(...),
    stawka_ryczaltu: str = Form("0.12"),
):
    """
    Asynchroniczne przeliczenie form opodatkowania w czasie rzeczywistym (HTMX suwaki).
    Zwraca zaktualizowany komponent wizualny i karty.
    """
    ctx = get_global_context(request)
    rok = ctx["rok"]

    przychod_dec = clean_decimal(przychod, "240000.00")
    koszt_dec = clean_decimal(koszt, "24000.00")
    stawka_dec = clean_decimal(stawka_ryczaltu, "0.12")

    comparison = simulate_tax_regimes(
        przychody_roczne=przychod_dec,
        koszty_roczne=koszt_dec,
        stawka_ryczaltu=stawka_dec,
        rok=rok,
    )

    result_ctx = {
        "request": request,
        "comparison": comparison,
        "przychod": przychod_dec,
        "koszt": koszt_dec,
        "stawka_ryczaltu": stawka_dec,
    }
    return templates.TemplateResponse(request=request, name="partials/advisor_simulation_result.html", context=result_ctx)
