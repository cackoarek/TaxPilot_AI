"""
src/web/routers/settlement.py
Kontroler Wstępnego Przeglądu Dokumentów (Pre-settlement Review) i zamykania miesiąca.
"""
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Form, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context
from src.skills.pre_settlement_review import PreSettlementReview, ExpenseItemReview
from src.skills.cost_classifier import (
    RegulyKosztoweFirmy,
    KwalifikacjaKosztu,
)
from src.level_3_tax_settlement.settlement_service import SettlementService

router = APIRouter(tags=["Rozliczenie & Przegląd"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/przeglad", response_class=HTMLResponse)
async def review_dashboard(request: Request):
    """Główny widok Wstępnego Przeglądu Dokumentów (Krok 2)."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    review = None
    if profile:
        review = PreSettlementReview.build(profile, rok, miesiac)

    ctx["review"] = review
    ctx["active_tab"] = "review"

    return templates.TemplateResponse(request=request, name="pages/review.html", context=ctx)


@router.post("/api/costs/qualify", response_class=HTMLResponse)
async def qualify_expense_item(
    request: Request,
    response: Response,
    lp: int = Query(...),
    numer: str = Query(...),
    kwalifikacja: str = Form(...),
    sprzedawca_nip: Optional[str] = Form(None),
    opis: Optional[str] = Form(None),
    zapisz_regule: bool = Form(False),
):
    """
    Zmiana kwalifikacji podatkowej wydatku (HTMX inline-editing).
    Zwraca zaktualizowany wiersz tabeli z nagłówkiem odświeżenia paska sum.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    # Jeśli użytkownik chce utrwalić regułę na przyszłość
    if zapisz_regule or kwalifikacja in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
        reguly = RegulyKosztoweFirmy.load(profile)
        wzorzec = opis.strip() if opis and opis.strip() else numer
        reguly.dodaj_regule(
            profile=profile,
            wzorzec=wzorzec,
            kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
            uzasadnienie="Kwalifikacja zaktualizowana przez przedsiębiorcę w UI",
            nip_kontrahenta=sprzedawca_nip.strip() if sprzedawca_nip else None,
        )

    # Przebudowanie przeglądu dla spójnych danych
    review = PreSettlementReview.build(profile, rok, miesiac)

    # Znalezienie konkretnego wydatku
    target_item = None
    for item in review.koszty:
        if item.lp == lp or item.numer == numer:
            target_item = item
            break

    if not target_item and review.koszty:
        target_item = review.koszty[0]

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary"},
    )


@router.get("/api/costs/summary", response_class=HTMLResponse)
async def get_costs_summary(request: Request):
    """Zwraca zaktualizowany pasek sum kosztów i VAT dla HTMX."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    review = PreSettlementReview.build(profile, rok, miesiac) if profile else None
    summary_ctx = {
        "request": request,
        "review": review,
    }
    return templates.TemplateResponse(request=request, name="partials/costs_summary.html", context=summary_ctx)


@router.post("/api/rules/save", response_class=HTMLResponse)
async def save_custom_rule(
    request: Request,
    wzorzec: str = Form(...),
    kwalifikacja: str = Form(...),
    sprzedawca_nip: Optional[str] = Form(None),
    uzasadnienie: Optional[str] = Form(None),
):
    """Utrwala regułę kosztową w pliku reguly_kosztowe.json."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    reguly = RegulyKosztoweFirmy.load(profile)
    reguly.dodaj_regule(
        profile=profile,
        wzorzec=wzorzec.strip(),
        kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
        uzasadnienie=uzasadnienie.strip() if uzasadnienie else "Zatwierdzono w UI TaxPilot",
        nip_kontrahenta=sprzedawca_nip.strip() if sprzedawca_nip else None,
    )

    return HTMLResponse(
        content="""
        <div class="p-3 bg-emerald-50 text-emerald-800 text-xs font-semibold rounded-lg border border-emerald-200 flex items-center space-x-2 fade-in">
            <span>✅</span>
            <span>Reguła została pomyślnie zapisana w <code>reguly_kosztowe.json</code>. Zastosowano dla kolejnych rozliczeń.</span>
        </div>
        """
    )


@router.post("/api/settlement/close")
async def close_month_settlement(
    request: Request,
    nadwyzka_vat: str = Form("0.00"),
):
    """
    Finalizuje rozliczenie miesiąca: uruchamia SettlementService i generuje oficjalne raporty.
    Przekierowuje na Pulpit (/).
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    try:
        nadwyzka_dec = Decimal(nadwyzka_vat.replace(" ", "").replace(",", "."))
    except Exception:
        nadwyzka_dec = Decimal("0.00")

    # Deterministyczne rozliczenie miesiąca w Pythonie
    SettlementService.settle_month(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        nadwyzka_vat_poprzedni=nadwyzka_dec,
        zapisz_raporty=True,
    )

    return RedirectResponse(url="/", status_code=303)
