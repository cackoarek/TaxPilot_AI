"""
src/web/routers/bookkeeping.py
Kontroler procesu księgowania (Księgowanie & Ewidencje Podatkowe).
Prezentuje podsumowanie dokumentów zakwalifikowanych do księgowania,
pozwala na deterministyczne zamykanie miesiąca i podgląd ewidencji księgowych.
"""

import json
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.level_3_tax_settlement.settlement_service import SettlementService
from src.logging_config import get_logger
from src.skills.pre_settlement_review import PreSettlementReview
from src.skills.zus_indicators import (
    calculate_zus_breakdown_preview,
    get_zus_indicators,
    is_official,
    update_zus_indicators,
)
from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context
from src.web.utils.markdown import render_markdown

logger = get_logger("taxpilot.bookkeeping")
router = APIRouter(prefix="/ksiegowanie", tags=["Księgowanie & Ewidencje"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["markdown"] = render_markdown


def _load_settlement_bundle(profile, rok: str, miesiac: str) -> Dict[str, Any]:
    """Ładuje dane i raporty rozliczenia jeśli zostały wygenerowane."""
    bundle: Dict[str, Any] = {
        "settlement": None,
        "ewidencja_md": None,
        "ewidencja_sumy_md": None,
        "sprawozdanie_md": None,
        "rozliczenie_md": None,
    }
    if not profile:
        return bundle

    settlement_dir = profile.katalog_firmy / "rozliczenia" / rok / miesiac
    json_file = settlement_dir / "rozliczenie.json"

    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                bundle["settlement"] = json.load(f)
        except Exception as e:
            logger.warning("Błąd odczytu %s: %s", json_file, e)

    md_files = {
        "ewidencja_md": "ewidencja-przychodow.md",
        "ewidencja_sumy_md": "ewidencja-przychodow-sumy.md",
        "sprawozdanie_md": "sprawozdanie.md",
        "rozliczenie_md": "rozliczenie.md",
    }
    for key, filename in md_files.items():
        p = settlement_dir / filename
        if p.exists():
            try:
                bundle[key] = p.read_text(encoding="utf-8")
            except Exception:
                pass

    return bundle


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def bookkeeping_dashboard(
    request: Request,
    sukces: Optional[str] = Query(None),
):
    """
    Główny widok modułu Księgowanie:
    - Podsumowanie dokumentów przeznaczonych do zaksięgowania (przychody, koszty, kwalifikacje)
    - Formularz uruchomienia deterministycznego księgowania
    - Podgląd wygenerowanych ewidencji podatkowych (Ewidencja przychodów, Rejestr VAT, Sumy YTD)
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    review = None
    if profile:
        try:
            review = PreSettlementReview.build(profile, rok, miesiac)
        except Exception as exc:
            logger.warning("Błąd budowania PreSettlementReview dla %s-%s: %s", rok, miesiac, exc)

    bundle = _load_settlement_bundle(profile, rok, miesiac)
    settlement_data = bundle["settlement"]
    is_settled = settlement_data is not None

    # Sprawdzenie gotowości do księgowania i metryk pozycji
    pozycje_do_wyjasnienia_cnt = len(review.do_wyjasnienia) if review else 0
    ready_to_settle = review is not None and (len(review.sprzedaz) > 0 or len(review.koszty) > 0)

    # Obliczenia podsumowujące kwalifikację kosztów i stawki ryczałtu
    kwalifikowany_vat = Decimal("0.00")
    odrzucony_vat = Decimal("0.00")
    wykluczone_pozycje_cnt = 0
    stawki_podsumowanie: Dict[Decimal, Decimal] = {}

    if review:
        for s in review.sprzedaz:
            st = s.stawka_ryczaltu
            stawki_podsumowanie[st] = stawki_podsumowanie.get(st, Decimal("0.00")) + s.kwota_netto

        for k in review.koszty:
            kwalifikowany_vat += getattr(k, "kwalifikowany_vat", Decimal("0.00"))
            odrz = getattr(k, "odrzucony_vat_prywatny", Decimal("0.00"))
            odrzucony_vat += odrz
            if odrz > 0:
                wykluczone_pozycje_cnt += 1

    # Wskaźniki makroekonomiczne ZUS/GUS dla aktywnego roku
    zus_macro = get_zus_indicators(rok)
    zus_preview = calculate_zus_breakdown_preview(zus_macro)
    is_zus_official = is_official(zus_macro)

    tab_param = request.query_params.get("tab")
    wskazniki_zapisane = request.query_params.get("wskazniki_zapisane") == "1"
    blad_wskaznikow = request.query_params.get("blad_wskaznikow") == "1"

    ewidencja_sumy_html = render_markdown(bundle["ewidencja_sumy_md"]) if bundle["ewidencja_sumy_md"] else None
    sprawozdanie_html = render_markdown(bundle["sprawozdanie_md"]) if bundle["sprawozdanie_md"] else None

    ctx.update(
        {
            "active_tab": "bookkeeping",
            "review": review,
            "is_settled": is_settled,
            "settlement": settlement_data,
            "ewidencja_md": bundle["ewidencja_md"],
            "ewidencja_sumy_md": bundle["ewidencja_sumy_md"],
            "ewidencja_sumy_html": ewidencja_sumy_html,
            "sprawozdanie_md": bundle["sprawozdanie_md"],
            "sprawozdanie_html": sprawozdanie_html,
            "rozliczenie_md": bundle["rozliczenie_md"],
            "pozycje_do_wyjasnienia_cnt": pozycje_do_wyjasnienia_cnt,
            "ready_to_settle": ready_to_settle,
            "kwalifikowany_vat": kwalifikowany_vat,
            "odrzucony_vat": odrzucony_vat,
            "wykluczone_pozycje_cnt": wykluczone_pozycje_cnt,
            "stawki_podsumowanie": stawki_podsumowanie,
            "sukces": sukces == "1",
            "zus_macro": zus_macro,
            "zus_preview": zus_preview,
            "is_zus_official": is_zus_official,
            "wskazniki_zapisane": wskazniki_zapisane,
            "blad_wskaznikow": blad_wskaznikow,
            "tab_param": tab_param,
        }
    )

    return templates.TemplateResponse(request=request, name="pages/bookkeeping.html", context=ctx)


@router.post("/uruchom")
async def execute_settlement(
    request: Request,
    nadwyzka_vat: str = Form("0.00"),
):
    """
    Uruchamia deterministyczne księgowanie i rozliczenie podatkowe miesiąca.
    Wykonuje silnik SettlementService i generuje oficjalne rejestry oraz paczkę przelewów.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    try:
        nadwyzka_dec = Decimal(nadwyzka_vat.replace(" ", "").replace(",", "."))
    except Exception:
        nadwyzka_dec = Decimal("0.00")

    logger.info(
        "Uruchamianie księgowania dla %s za %s-%s (nadwyżka VAT: %s)", profile.nazwa, rok, miesiac, nadwyzka_dec
    )

    SettlementService.settle_month(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        nadwyzka_vat_poprzedni=nadwyzka_dec,
        zapisz_raporty=True,
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get(
        "accept", ""
    )
    if is_ajax:
        return JSONResponse(
            {
                "status": "ok",
                "message": f"Miesiąc {rok}-{miesiac} został pomyślnie zaksięgowany!",
                "rok": rok,
                "miesiac": miesiac,
            }
        )

    return RedirectResponse(url="/ksiegowanie?sukces=1", status_code=303)


@router.post("/wskazniki-zus")
async def save_zus_macro_indicators(
    request: Request,
    rok: str = Form(...),
    podstawa_pelny_zus: str = Form(...),
    podstawa_preferencyjny_zus: str = Form(...),
    przecietne_wynagrodzenie_zdrowotna: str = Form(...),
    akceptuj_prognoze: Optional[str] = Form(None),
):
    """
    Zapisuje zweryfikowane lub zmodyfikowane wskaźniki makroekonomiczne ZUS/GUS dla danego roku.
    """

    def _parse(val: str) -> Decimal:
        cleaned = val.replace(" ", "").replace(",", ".").replace("zł", "").strip()
        return Decimal(cleaned)

    try:
        spol = _parse(podstawa_pelny_zus)
        pref = _parse(podstawa_preferencyjny_zus)
        zdrow = _parse(przecietne_wynagrodzenie_zdrowotna)
        zrodlo = "ZWERYFIKOWANE" if akceptuj_prognoze else "WPROWADZONE_RECZNIE"

        update_zus_indicators(
            rok=rok,
            podstawa_pelny_zus=spol,
            podstawa_preferencyjny_zus=pref,
            przecietne_wynagrodzenie_zdrowotna=zdrow,
            zrodlo=zrodlo,
        )
        logger.info(
            "Zaktualizowano wskaźniki ZUS dla roku %s: pełny=%s, pref=%s, zdrow=%s, źródło=%s",
            rok,
            spol,
            pref,
            zdrow,
            zrodlo,
        )
    except Exception as exc:
        logger.error("Błąd zapisu wskaźników ZUS dla roku %s: %s", rok, exc)
        return RedirectResponse(url="/ksiegowanie?blad_wskaznikow=1&tab=wskazniki", status_code=303)

    return RedirectResponse(url="/ksiegowanie?wskazniki_zapisane=1&tab=wskazniki", status_code=303)
