"""
src/web/routers/invoices.py
Kontroler Magazynu Dokumentów: przeglądanie faktur KSeF/Non-KSeF, upload Drag&Drop,
auto-routing oraz wywołanie synchronizacji z KSeF 2.0.
"""
import os
import re
import shutil
from pathlib import Path
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Request, Form, UploadFile, File, Query, HTTPException, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.core.invoice import Invoice, InvoiceType
from src.core.company import CompanyProfile
from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.level_1_ingestion.ksef_client import KSeFClient

router = APIRouter(prefix="/faktury", tags=["Magazyn Faktur & KSeF"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ALLOWED_EXTENSIONS = {".pdf", ".json", ".txt", ".md", ".jpg", ".jpeg", ".png"}


def get_month_invoices_summary(profile: CompanyProfile, rok: str, miesiac: str, typ_filter: Optional[str] = None) -> Dict[str, Any]:
    """Zbiera wszystkie faktury, statystyki i relokacje dla wybranego miesiąca."""
    typ_enum = None
    if typ_filter == "sprzedaz":
        typ_enum = InvoiceType.SPRZEDAZ
    elif typ_filter == "koszty":
        typ_enum = InvoiceType.KOSZT

    all_invoices = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=typ_enum)

    sprzedaz_invoices = [i for i in all_invoices if i.typ == InvoiceType.SPRZEDAZ]
    koszty_invoices = [i for i in all_invoices if i.typ == InvoiceType.KOSZT]

    suma_sprzedaz_netto = sum((i.suma_netto for i in sprzedaz_invoices), Decimal("0.00"))
    suma_sprzedaz_vat = sum((i.suma_vat for i in sprzedaz_invoices), Decimal("0.00"))
    suma_koszty_netto = sum((i.suma_netto for i in koszty_invoices), Decimal("0.00"))
    suma_koszty_vat = sum((i.suma_vat for i in koszty_invoices), Decimal("0.00"))

    ksef_count = sum(1 for i in all_invoices if i.zrodlo == "KSEF" or i.ksef_numer_referencyjny)
    non_ksef_count = len(all_invoices) - ksef_count

    # Sprawdzenie znaczników relokacji Auto-Routing (*.PRZENIESIONO.txt)
    relokacje = []
    for check_type in [InvoiceType.SPRZEDAZ, InvoiceType.KOSZT]:
        raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=check_type)
        if raw_dir.exists():
            for marker in raw_dir.glob("*.PRZENIESIONO.txt"):
                try:
                    relokacje.append({
                        "plik": marker.name.replace(".PRZENIESIONO.txt", ""),
                        "katalog": check_type.value,
                        "tresc": marker.read_text(encoding="utf-8")
                    })
                except Exception:
                    pass

    return {
        "invoices": all_invoices,
        "sprzedaz": sprzedaz_invoices,
        "koszty": koszty_invoices,
        "suma_sprzedaz_netto": suma_sprzedaz_netto,
        "suma_sprzedaz_vat": suma_sprzedaz_vat,
        "suma_koszty_netto": suma_koszty_netto,
        "suma_koszty_vat": suma_koszty_vat,
        "ksef_count": ksef_count,
        "non_ksef_count": non_ksef_count,
        "relokacje": relokacje,
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def invoices_dashboard(
    request: Request,
    tab: str = Query("all", pattern="^(all|sprzedaz|koszty)$"),
):
    """Główny widok Magazynu Faktur."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    summary = None
    if profile:
        summary = get_month_invoices_summary(profile, rok, miesiac, typ_filter=tab if tab != "all" else None)

    ctx["summary"] = summary
    ctx["tab"] = tab
    ctx["active_tab"] = "invoices"

    return templates.TemplateResponse(request=request, name="pages/invoices.html", context=ctx)


@router.post("/upload", response_class=HTMLResponse)
async def upload_invoice_file(
    request: Request,
    file: UploadFile = File(...),
    kategoria: str = Form("koszt"),  # "koszt" lub "sprzedaz"
):
    """
    Obsługa uploadu pliku dokumentu (Drag & Drop lub formularz).
    Zapisuje plik w non-ksef-raw, uruchamia dwuetapową ekstrakcję z auto-routingiem
    i zwraca zaktualizowany fragment tabeli lub alert.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    filename = Path(file.filename).name
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        return HTMLResponse(
            content=f"""
            <div class="p-3 bg-red-50 text-red-800 text-xs font-semibold rounded-lg border border-red-200 flex items-center space-x-2">
                <span>⛔</span>
                <span>Niedozwolony format pliku: <code>{ext}</code>. Dozwolone: PDF, JSON, TXT, JPG, PNG.</span>
            </div>
            """,
            status_code=400,
        )

    target_type = InvoiceType.SPRZEDAZ if kategoria.lower() == "sprzedaz" else InvoiceType.KOSZT
    raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=target_type)
    dest_path = raw_dir / filename

    # Zapis surowych bajtów dokumentu
    content_bytes = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content_bytes)

    # Uruchomienie deterministycznej ekstrakcji Non-KSeF z auto-routingiem
    extracted_paths = NonKSeFExtractor.extract_all(profile, rok, miesiac, force=True)

    # Sprawdzenie czy plik został zrelokowany (np. omyłkowa sprzedaż w kosztach)
    relokowany = False
    marker_path = raw_dir / f"{filename}.PRZENIESIONO.txt"
    if marker_path.exists():
        relokowany = True

    msg = f"Dokument <strong>{filename}</strong> został pomyślnie wgrany i wyekstrahowany."
    if relokowany:
        msg = (
            f"⚠️ <strong>Auto-Routing:</strong> Dokument <strong>{filename}</strong> zawierał fakturę innego typu "
            f"niż wskazany ({kategoria}). Został automatycznie przeniesiony do właściwego folderu."
        )

    alert_html = f"""
    <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
        <div class="flex items-center space-x-2 font-bold">
            <span>✅</span>
            <span>Przetworzono dokument pomyślnie</span>
        </div>
        <div>{msg}</div>
    </div>
    """

    # Zwrócenie zaktualizowanej tabeli faktur
    summary = get_month_invoices_summary(profile, rok, miesiac)
    render_ctx = {
        "request": request,
        "summary": summary,
        "tab": "all",
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "upload_alert": alert_html,
    }
    return templates.TemplateResponse(request=request, name="partials/invoices_table.html", context=render_ctx)


@router.post("/ksef-sync", response_class=HTMLResponse)
async def sync_ksef_invoices(request: Request):
    """Wywołuje synchronizację z KSeF 2.0 dla wybranego miesiąca."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    client = KSeFClient(profile)

    if not client.is_token_configured():
        return HTMLResponse(
            content="""
            <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-2 shadow-xs fade-in mb-4">
                <div class="flex items-center space-x-2 font-bold">
                    <span>⚠️</span>
                    <span>Brak skonfigurowanego tokenu KSeF</span>
                </div>
                <p>Aby pobierać faktury bezpośrednio z KSeF, uzupełnij token autoryzacyjny w pliku <code>profil.json</code> firmy lub w module Ustawienia.</p>
            </div>
            """
        )

    try:
        res = client.sync_month_invoices(rok, miesiac)
        liczba_s = res.get("liczba_sprzedazy", 0)
        liczba_k = res.get("liczba_kosztow", 0)
        alert_html = f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
            <div class="flex items-center space-x-2 font-bold">
                <span>🏛️</span>
                <span>Synchronizacja KSeF 2.0 zakończona sukcesem</span>
            </div>
            <p>Zsynchronizowano za okres {rok}-{miesiac}: <strong>{liczba_s}</strong> faktur sprzedaży oraz <strong>{liczba_k}</strong> faktur kosztowych.</p>
        </div>
        """
    except Exception as e:
        alert_html = f"""
        <div class="p-4 bg-rose-50 text-rose-900 border border-rose-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
            <div class="flex items-center space-x-2 font-bold">
                <span>❌</span>
                <span>Błąd połączenia z Krajowym Systemem e-Faktur</span>
            </div>
            <p class="font-mono text-[11px]">{str(e)}</p>
            <p class="text-[11px] text-rose-700">Upewnij się, że masz połączenie z Internetem i token środowiska KSeF ({profile.ksef.srodowisko}) jest ważny.</p>
        </div>
        """

    summary = get_month_invoices_summary(profile, rok, miesiac)
    render_ctx = {
        "request": request,
        "summary": summary,
        "tab": "all",
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "upload_alert": alert_html,
    }
    return templates.TemplateResponse(request=request, name="partials/invoices_table.html", context=render_ctx)


@router.get("/download")
async def download_invoice_file(
    request: Request,
    sciezka: str = Query(...),
):
    """
    Bezpieczne pobieranie pliku dokumentu faktury.
    Chroni przed atakami Path Traversal poprzez walidację katalogu firmy.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    # Bezpieczne rozwiązanie ścieżki
    target_path = Path(sciezka).resolve()
    company_root = profile.katalog_firmy.resolve()

    # Walidacja: ścieżka MUSI znajdować się wewnątrz katalogu aktywnej firmy
    try:
        target_path.relative_to(company_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Dostęp zabroniony: Próba nieautoryzowanego odczytu spoza katalogu firmy.")

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Plik faktury nie został odnaleziony na dysku.")

    return FileResponse(
        path=str(target_path),
        filename=target_path.name,
        media_type="application/octet-stream",
    )
