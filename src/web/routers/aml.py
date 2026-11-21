"""
src/web/routers/aml.py
Kontroler modułu AML, Białej Listy VAT i Należytej Staranności.
"""

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from src.skills.aml_tools import (
    AMLVerificationEngine,
    VerificationService,
)
from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context

router = APIRouter(prefix="/aml", tags=["Compliance AML"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def load_monthly_aml_report(profile, rok: str, miesiac: str) -> Optional[Dict[str, Any]]:
    """Ładuje stan raportu z weryfikacje/{rok}/{miesiac}/raport-weryfikacji.json."""
    if not profile:
        return None
    report_file = profile.katalog_firmy / "weryfikacje" / rok / miesiac / "raport-weryfikacji.json"
    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                st = data.setdefault("statystyki", {})
                st.setdefault("bledy_polaczenia_offline", 0)
                st.setdefault("zweryfikowani_kontrahenci", 0)
                st.setdefault("niski_ryzyko_akceptacja", 0)
                st.setdefault("niskie_ryzyko_zielone", 0)
                st.setdefault("srednie_ryzyko_uwaga", 0)
                st.setdefault("wysokie_ryzyko_wyjasnienia", 0)
                st.setdefault("krytyczne_stop_sankcje", 0)
            return data
        except Exception:
            return None
    return None


@router.get("", response_class=HTMLResponse)
async def aml_dashboard(request: Request):
    """Główny widok centrum weryfikacji AML i Białej Listy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    report_data = load_monthly_aml_report(profile, rok, miesiac)
    ctx["report_data"] = report_data
    ctx["active_tab"] = "aml"

    return templates.TemplateResponse(request=request, name="pages/aml.html", context=ctx)


@router.post("/verify", response_class=HTMLResponse)
async def verify_contractor_adhoc(
    request: Request,
    nip: str = Form(...),
    rachunek: Optional[str] = Form(None),
    kwota: Optional[str] = Form(None),
    force: bool = Form(False),
):
    """
    Weryfikacja pojedynczego kontrahenta ad-hoc (wywoływana przez HTMX).
    Zwraca fragment HTML partials/aml_card_result.html.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]

    kwota_dec = None
    if kwota and kwota.strip():
        try:
            kwota_clean = kwota.replace(" ", "").replace(",", ".")
            kwota_dec = Decimal(kwota_clean)
        except InvalidOperation:
            pass

    rachunek_clean = rachunek.strip() if rachunek and rachunek.strip() else None

    # Deterministyczna weryfikacja w silniku Python AML
    karta = AMLVerificationEngine.verify_contractor(
        nip=nip.strip(),
        rachunek_bankowy=rachunek_clean,
        kwota_transakcji=kwota_dec,
        profile=profile,
        force=force,
    )

    # Upewnienie się, że plik PDF karty istnieje
    if profile:
        rok = ctx["rok"]
        miesiac = ctx["miesiac"]
        cards_dir = profile.katalog_firmy / "weryfikacje" / rok / miesiac / "karty"
        cards_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = cards_dir / f"{karta.nip}-karta.pdf"
        try:
            karta.generate_pdf_card(pdf_path)
        except Exception:
            pass

    card_ctx = {
        "request": request,
        "karta": karta,
        "rok": ctx["rok"],
        "miesiac": ctx["miesiac"],
    }
    return templates.TemplateResponse(request=request, name="partials/aml_card_result.html", context=card_ctx)


@router.post("/verify-month", response_class=HTMLResponse)
async def verify_month_batch(
    request: Request,
    force: bool = Form(False),
):
    """
    Uruchamia zbiorczą procedurę należytej staranności dla wszystkich faktur miesiąca.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    # Uruchomienie VerificationService
    VerificationService.verify_month(profile, rok, miesiac, zapisz_pliki=True, force=force)

    # Przeładowanie widoku tabeli i podsumowania
    report_data = load_monthly_aml_report(profile, rok, miesiac)
    ctx["report_data"] = report_data

    return templates.TemplateResponse(request=request, name="partials/aml_table_rows.html", context=ctx)


@router.get("/karta/pdf/{nip}")
async def download_contractor_card_pdf(
    nip: str,
    request: Request,
    rok: Optional[str] = Query(None),
    miesiac: Optional[str] = Query(None),
):
    """Pobieranie oficjalnej Karty Weryfikacji Kontrahenta w formacie PDF."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    if not profile:
        raise HTTPException(status_code=404, detail="Brak profilu firmy")

    r = rok or ctx["rok"]
    m = miesiac or ctx["miesiac"]
    clean_nip = AMLVerificationEngine.clean_nip(nip)

    pdf_path = profile.katalog_firmy / "weryfikacje" / r / m / "karty" / f"{clean_nip}-karta.pdf"

    if not pdf_path.exists():
        # Generowanie na żądanie
        karta = AMLVerificationEngine.verify_contractor(nip=clean_nip, profile=profile)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        karta.generate_pdf_card(pdf_path)

    return FileResponse(
        path=str(pdf_path),
        filename=f"karta-weryfikacji-{clean_nip}.pdf",
        media_type="application/pdf",
    )


@router.get("/raport/pdf")
async def download_monthly_report_pdf(
    request: Request,
    rok: Optional[str] = Query(None),
    miesiac: Optional[str] = Query(None),
):
    """Pobieranie zbiorczego miesięcznego raportu należytej staranności w formacie PDF (A4 pejzaż)."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    if not profile:
        raise HTTPException(status_code=404, detail="Brak profilu firmy")

    r = rok or ctx["rok"]
    m = miesiac or ctx["miesiac"]
    pdf_path = profile.katalog_firmy / "weryfikacje" / r / m / "raport-weryfikacji.pdf"

    if not pdf_path.exists():
        # Wygenerowanie raportu jeśli brak
        VerificationService.verify_month(profile, r, m, zapisz_pliki=True)

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Nie udało się wygenerować raportu PDF")

    return FileResponse(
        path=str(pdf_path),
        filename=f"raport-weryfikacji-aml-{r}-{m}.pdf",
        media_type="application/pdf",
    )


@router.get("/raport/md")
async def download_monthly_report_md(
    request: Request,
    rok: Optional[str] = Query(None),
    miesiac: Optional[str] = Query(None),
):
    """Pobieranie zbiorczego raportu weryfikacji w formacie Markdown."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    if not profile:
        raise HTTPException(status_code=404, detail="Brak profilu firmy")

    r = rok or ctx["rok"]
    m = miesiac or ctx["miesiac"]
    md_path = profile.katalog_firmy / "weryfikacje" / r / m / "raport-weryfikacji.md"

    if not md_path.exists():
        VerificationService.verify_month(profile, r, m, zapisz_pliki=True)

    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Brak raportu Markdown")

    return FileResponse(
        path=str(md_path),
        filename=f"raport-weryfikacji-aml-{r}-{m}.md",
        media_type="text/markdown",
    )
