"""
src/web/routers/invoices.py
Kontroler Magazynu Dokumentów: przeglądanie faktur KSeF/Non-KSeF, upload Drag&Drop,
auto-routing oraz wywołanie synchronizacji z KSeF 2.0.
"""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType
from src.core.io import atomic_write_bytes
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.logging_config import get_logger
from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context

logger = get_logger("taxpilot.invoices")
router = APIRouter(prefix="/faktury", tags=["Magazyn Faktur & KSeF"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

ALLOWED_EXTENSIONS = {".pdf", ".json", ".txt", ".md", ".jpg", ".jpeg", ".png"}

# Limity uploadu (ochrona przed DoS pamięciowym i wyczerpaniem dysku)
MAX_SINGLE_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
MAX_TOTAL_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
CHUNK_SIZE = 64 * 1024  # 64 KB bufor odczytu strumieniowego


def sanitize_filename(raw_filename: str) -> str:
    """
    Sanityzuje nazwę pliku, usuwając sekwencje path traversal oraz niebezpieczne znaki.
    Normalizuje nazwę do znaków bezpiecznych [a-zA-Z0-9._-].
    """
    normalized = raw_filename.strip().replace("\\", "/").split("/")[-1]
    stem = Path(normalized).stem
    ext = Path(normalized).suffix.lower()
    clean_stem = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)
    clean_stem = re.sub(r"_+", "_", clean_stem).strip("._-")
    if not clean_stem:
        clean_stem = "dokument"
    return f"{clean_stem}{ext}"


def validate_file_content(content: bytes, ext: str) -> Tuple[bool, str]:
    """
    Weryfikuje rzeczywistą zawartość pliku na podstawie nagłówków (Magic Bytes).
    Chroni przed wstrzyknięciem plików wykonywalnych ze zmienionym rozszerzeniem.
    """
    if not content:
        return False, "Plik jest pusty (0 bajtów)"

    ext_clean = ext.lower().strip()

    if ext_clean == ".pdf":
        if not (content.startswith(b"%PDF-") or b"%PDF-" in content[:1024]):
            return False, "Brak poprawnej sygnatury PDF (%PDF-)"
        # Głęboka inspekcja PDF: blokowanie złośliwych dyrektyw uruchomieniowych (SEC-5)
        lower_content = content.lower()
        for dangerous_tag in (b"/javascript", b"/js", b"/launch", b"/embeddedfiles"):
            if dangerous_tag in lower_content:
                return (
                    False,
                    f"Odrzucono plik PDF: wykryto niebezpieczną zawartość aktywną ({dangerous_tag.decode('ascii')})",
                )
        return True, ""

    if ext_clean == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, "Brak poprawnej sygnatury obrazu PNG"
        return True, ""

    if ext_clean in (".jpg", ".jpeg"):
        if not content.startswith(b"\xff\xd8\xff"):
            return False, "Brak poprawnej sygnatury obrazu JPEG"
        return True, ""

    if ext_clean == ".json":
        try:
            parsed = json.loads(content.decode("utf-8"))
            if not isinstance(parsed, (dict, list)):
                return False, "JSON musi zawierać obiekt lub listę"
            return True, ""
        except Exception as e:
            return False, f"Niepoprawny format JSON: {e}"

    if ext_clean in (".txt", ".md"):
        if b"\x00" in content:
            return False, "Wykryto zawartość binarną w pliku tekstowym"
        # Ochrona przed wstrzykiwaniem niebezpiecznego HTML / skryptów w plikach tekstowych (SEC-5)
        lower_content = content.lower()
        for forbidden in (b"<script", b"<iframe", b"<object", b"<embed"):
            if forbidden in lower_content:
                return False, "Odrzucono plik tekstowy: wykryto niedozwolone znaczniki kodu wykonywalnego HTML/JS"
        try:
            content.decode("utf-8")
            return True, ""
        except UnicodeDecodeError:
            try:
                content.decode("cp1250")
                return True, ""
            except Exception:
                return False, "Brak poprawnego kodowania tekstowego UTF-8 / CP1250"

    return False, f"Nieobsługiwany format zawartości {ext}"


def get_month_invoices_summary(
    profile: CompanyProfile, rok: str, miesiac: str, typ_filter: Optional[str] = None
) -> Dict[str, Any]:
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
                    relokacje.append(
                        {
                            "plik": marker.name.replace(".PRZENIESIONO.txt", ""),
                            "katalog": check_type.value,
                            "tresc": marker.read_text(encoding="utf-8"),
                        }
                    )
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
    last_sync = None
    sync_history = []
    if profile:
        summary = get_month_invoices_summary(profile, rok, miesiac, typ_filter=tab if tab != "all" else None)
        last_sync = KSeFClient.get_last_sync(profile, rok, miesiac)
        sync_history = KSeFClient.load_sync_history(profile)

    ctx["summary"] = summary
    ctx["last_sync"] = last_sync
    ctx["sync_history"] = sync_history
    ctx["tab"] = tab
    ctx["active_tab"] = "invoices"

    return templates.TemplateResponse(request=request, name="pages/invoices.html", context=ctx)


@router.get("/table", response_class=HTMLResponse)
async def invoices_table_partial(
    request: Request,
    tab: Optional[str] = Query("all"),
):
    """Zwraca odświeżony fragment tabeli dokumentów (dla HTMX events np. invoices-refresh)."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    tab_clean = tab if tab in ("all", "sprzedaz", "koszty") else "all"
    summary = None
    last_sync = None
    sync_history = []
    if profile:
        summary = get_month_invoices_summary(
            profile, rok, miesiac, typ_filter=tab_clean if tab_clean != "all" else None
        )
        last_sync = KSeFClient.get_last_sync(profile, rok, miesiac)
        sync_history = KSeFClient.load_sync_history(profile)

    render_ctx = {
        "request": request,
        "summary": summary,
        "tab": tab_clean,
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "last_sync": last_sync,
        "sync_history": sync_history,
        "upload_alert": None,
    }
    return templates.TemplateResponse(request=request, name="partials/invoices_table.html", context=render_ctx)


@router.post("/upload", response_class=HTMLResponse)
async def upload_invoice_file(
    request: Request,
    files: Optional[List[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
    kategoria: str = Form("koszt"),  # "koszt" lub "sprzedaz"
):
    """
    Obsługa uploadu dokumentów spoza KSeF (wielo-plikowy Drag & Drop lub formularz).
    Zapisuje pliki w non-ksef-raw, uruchamia dwuetapową ekstrakcję z auto-routingiem
    i zwraca zaktualizowany fragment tabeli z raportem.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    # Zbierz wszystkie przekazane pliki (zarówno z 'files' jak i wstecznie z 'file')
    all_files: List[UploadFile] = []
    if files:
        for f in files:
            if f and f.filename and f.filename.strip():
                all_files.append(f)
    if file and file.filename and file.filename.strip() and file not in all_files:
        all_files.append(file)

    if not all_files:
        alert_html = """
        <div class="p-3 bg-amber-50 text-amber-800 text-xs font-semibold rounded-lg border border-amber-200 flex items-center space-x-2 mb-4">
            <span>⚠️</span>
            <span>Nie wybrano żadnego pliku do wgrania. Wybierz lub przeciągnij pliki PDF, JSON, JPG lub PNG.</span>
        </div>
        """
        summary = get_month_invoices_summary(profile, rok, miesiac)
        from src.level_1_ingestion.extraction_service import ExtractionService

        unprocessed = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
        ext_status = ExtractionService.get_task_status(profile, rok, miesiac)
        return templates.TemplateResponse(
            request=request,
            name="partials/invoices_table.html",
            context={
                "request": request,
                "summary": summary,
                "tab": "all",
                "profile": profile,
                "rok": rok,
                "miesiac": miesiac,
                "upload_alert": alert_html,
                "unprocessed_invoices": unprocessed,
                "unprocessed_count": len(unprocessed),
                "extraction_status": ext_status,
                "banner_swap_oob": True,
            },
        )

    target_type = InvoiceType.SPRZEDAZ if kategoria.lower() == "sprzedaz" else InvoiceType.KOSZT
    raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=target_type)

    saved_files: List[str] = []
    rejected_files: List[tuple] = []
    relocated_files: List[str] = []
    size_exceeded_files: List[tuple] = []
    total_upload_size = 0

    for f in all_files:
        raw_name = f.filename or "nieznany_plik"
        ext = Path(raw_name).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            rejected_files.append((raw_name, f"Niedozwolony format {ext}"))
            continue

        clean_filename = sanitize_filename(raw_name)

        # Bezpieczny odczyt strumieniowy z twardym limitem pamięciowym
        try:
            chunks: List[bytes] = []
            file_size = 0
            while True:
                chunk = await f.read(CHUNK_SIZE)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > MAX_SINGLE_FILE_SIZE:
                    raise ValueError("Plik przekracza dopuszczalny limit 15 MB")
                if total_upload_size + file_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise ValueError("Łączny rozmiar paczki plików przekracza dopuszczalny limit 50 MB")
                chunks.append(chunk)

            content_bytes = b"".join(chunks)
            total_upload_size += file_size
        except ValueError as ve:
            size_exceeded_files.append((raw_name, str(ve)))
            continue

        # Weryfikacja Magic Bytes (rzeczywistej zawartości)
        is_valid, error_msg = validate_file_content(content_bytes, ext)
        if not is_valid:
            rejected_files.append((raw_name, error_msg))
            continue

        dest_path = raw_dir / clean_filename
        atomic_write_bytes(dest_path, content_bytes, mode=0o600)
        saved_files.append(clean_filename)

    # Uruchomienie ekstrakcji dla zapisanych plików
    if saved_files:
        try:
            NonKSeFExtractor.extract_all(profile, rok, miesiac, force=True)
        except Exception as e:
            logger.error("Błąd podczas ekstrakcji Non-KSeF: %s", e)

        for filename in saved_files:
            marker_path = raw_dir / f"{filename}.PRZENIESIONO.txt"
            if marker_path.exists():
                relocated_files.append(filename)

    # Budowanie komunikatu
    alert_parts = []
    if saved_files:
        count = len(saved_files)
        msg_title = f"Przetworzono dokument pomyślnie (wgrano {count} {'plik' if count == 1 else 'pliki' if count < 5 else 'plików'})"
        files_html = ", ".join([f"<strong>{fn}</strong>" for fn in saved_files])
        reloc_msg = ""
        if relocated_files:
            reloc_msg = f"<div class='mt-1 text-blue-800'>📁 <strong>Auto-Routing:</strong> Zrelokowano do właściwej kategorii: {', '.join(relocated_files)}.</div>"

        alert_parts.append(f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
            <div class="flex items-center space-x-2 font-bold">
                <span>✅</span>
                <span>{msg_title}</span>
            </div>
            <div>Przetworzone pliki: {files_html}</div>
            {reloc_msg}
        </div>
        """)

    if size_exceeded_files:
        size_html = ", ".join([f"<strong>{fn}</strong> ({err})" for fn, err in size_exceeded_files])
        alert_parts.append(f"""
        <div class="p-4 bg-red-50 text-red-900 border border-red-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
            <div class="flex items-center space-x-2 font-bold">
                <span>⛔</span>
                <span>Przekroczono limit rozmiaru plików – pominięto:</span>
            </div>
            <div>{size_html}. Limit: 15 MB na plik, 50 MB łącznie na paczkę.</div>
        </div>
        """)

    if rejected_files:
        rej_html = ", ".join([f"<strong>{fn}</strong> ({reason})" for fn, reason in rejected_files])
        alert_parts.append(f"""
        <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-1 shadow-xs fade-in mb-4">
            <div class="flex items-center space-x-2 font-bold">
                <span>⚠️</span>
                <span>Niedozwolony format lub błędna sygnatura pliku – pominięto:</span>
            </div>
            <div>{rej_html}. Dozwolone formaty: PDF, JSON, TXT, JPG, PNG.</div>
        </div>
        """)

    # Jeśli wystąpiło przekroczenie limitu rozmiaru i nie zapisano żadnego pliku -> HTTP 413
    if not saved_files and size_exceeded_files:
        size_err = ", ".join([f"<code>{fn}</code> ({err})" for fn, err in size_exceeded_files])
        return HTMLResponse(
            content=f"""
            <div class="p-3 bg-red-50 text-red-800 text-xs font-semibold rounded-lg border border-red-200 flex items-center space-x-2">
                <span>⛔</span>
                <span>Przekroczono dopuszczalny limit rozmiaru: {size_err}. Maksymalny rozmiar pliku to 15 MB (łączny limit: 50 MB).</span>
            </div>
            """,
            status_code=413,
        )

    # Jeśli nie zapisano żadnego pliku z powodu niedozwolonych rozszerzeń lub błędnych sygnatur -> HTTP 400
    if not saved_files and rejected_files:
        rej_details = ", ".join([f"<code>{fn}</code> ({reason})" for fn, reason in rejected_files])
        return HTMLResponse(
            content=f"""
            <div class="p-3 bg-red-50 text-red-800 text-xs font-semibold rounded-lg border border-red-200 flex items-center space-x-2">
                <span>⛔</span>
                <span>Niedozwolony format pliku lub niepoprawna sygnatura: {rej_details}. Dozwolone formaty: PDF, JSON, TXT, JPG, PNG.</span>
            </div>
            """,
            status_code=400,
        )

    alert_html = "".join(alert_parts)
    summary = get_month_invoices_summary(profile, rok, miesiac)

    from src.level_1_ingestion.extraction_service import ExtractionService

    unprocessed = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
    ext_status = ExtractionService.get_task_status(profile, rok, miesiac)

    render_ctx = {
        "request": request,
        "summary": summary,
        "tab": "all",
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "upload_alert": alert_html,
        "unprocessed_invoices": unprocessed,
        "unprocessed_count": len(unprocessed),
        "extraction_status": ext_status,
        "banner_swap_oob": True,
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
        KSeFClient.record_sync_attempt(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            status="BLAD",
            srodowisko=profile.ksef.srodowisko,
            komunikat=str(e),
        )
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
    last_sync = KSeFClient.get_last_sync(profile, rok, miesiac)
    sync_history = KSeFClient.load_sync_history(profile)

    render_ctx = {
        "request": request,
        "summary": summary,
        "tab": "all",
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "upload_alert": alert_html,
        "last_sync": last_sync,
        "sync_history": sync_history,
        "is_ksef_sync_response": True,
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
        raise HTTPException(
            status_code=403, detail="Dostęp zabroniony: Próba nieautoryzowanego odczytu spoza katalogu firmy."
        )

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Plik faktury nie został odnaleziony na dysku.")

    return FileResponse(
        path=str(target_path),
        filename=target_path.name,
        media_type="application/octet-stream",
    )


@router.post("/extract-ai", response_class=HTMLResponse)
async def trigger_ai_extraction(request: Request):
    """
    Uruchamia asynchroniczne wyciąganie danych z nieodczytanych faktur w tle.
    Proces wykonuje się niezależnie od nawigacji użytkownika.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    from src.level_1_ingestion.extraction_service import ExtractionService

    ExtractionService.start_ai_extraction(profile, rok, miesiac)

    # Odśwież stan kontekstu
    ctx["extraction_status"] = ExtractionService.get_task_status(profile, rok, miesiac)
    ctx["unprocessed_invoices"] = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
    ctx["unprocessed_count"] = len(ctx["unprocessed_invoices"])

    return templates.TemplateResponse(
        request=request,
        name="partials/unprocessed_invoices_banner.html",
        context=ctx,
    )


@router.get("/extract-status", response_class=HTMLResponse)
async def check_ai_extraction_status(request: Request):
    """
    Zwraca aktualny stan asynchronicznego zadania ekstrakcji AI.
    Odpytywany przez HTMX co określony interwał podczas trwania zadania.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    headers = {}
    if profile:
        from src.level_1_ingestion.extraction_service import ExtractionService

        ext_status = ExtractionService.get_task_status(profile, rok, miesiac)
        ctx["extraction_status"] = ext_status
        ctx["unprocessed_invoices"] = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
        ctx["unprocessed_count"] = len(ctx["unprocessed_invoices"])

        # Jeśli zadanie zakończyło się sukcesem, wyzwól odświeżenie tabeli faktur
        # i dołącz zaktualizowaną tabelę przez OOB swap
        if ext_status.get("status") == "completed":
            headers["HX-Trigger"] = "invoices-refresh"
            summary = get_month_invoices_summary(profile, rok, miesiac)
            ctx["summary"] = summary
            ctx["tab"] = "all"
            ctx["table_swap_oob"] = True

    return templates.TemplateResponse(
        request=request,
        name="partials/unprocessed_invoices_banner.html",
        context=ctx,
        headers=headers,
    )


@router.post("/extract-status/dismiss", response_class=HTMLResponse)
async def dismiss_ai_extraction_status(request: Request):
    """
    Resetuje status zadania po zakończeniu lub błędzie i ukrywa powiadomienie.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if profile:
        from src.level_1_ingestion.extraction_service import ExtractionService

        ExtractionService.clear_task_status(profile, rok, miesiac)
        ctx["extraction_status"] = {"status": "idle", "message": ""}
        ctx["unprocessed_invoices"] = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
        ctx["unprocessed_count"] = len(ctx["unprocessed_invoices"])

    return templates.TemplateResponse(
        request=request,
        name="partials/unprocessed_invoices_banner.html",
        context=ctx,
    )
