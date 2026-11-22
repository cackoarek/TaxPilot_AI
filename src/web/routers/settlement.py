"""
src/web/routers/settlement.py
Kontroler Wstępnego Przeglądu Dokumentów (Pre-settlement Review) i zamykania miesiąca.
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.level_3_tax_settlement.settlement_service import SettlementService
from src.logging_config import get_logger
from src.skills.cost_classifier import (
    CostClassifier,
    KwalifikacjaKosztu,
    ReczneKwalifikacjeService,
    RegulyKosztoweFirmy,
)
from src.skills.pre_settlement_review import PreSettlementReview
from src.web.config import TEMPLATES_DIR
from src.web.dependencies import get_global_context

logger = get_logger("taxpilot.settlement")
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
    ai_status = None
    liczba_regul = 0
    if profile:
        from src.web.services.ai_cost_qualifier import AICostQualifierService

        review = PreSettlementReview.build(profile, rok, miesiac)
        ai_status = AICostQualifierService.get_status(profile.nip, rok, miesiac)
        reguly = RegulyKosztoweFirmy.load(profile)
        liczba_regul = len(reguly.pobierz_wszystkie_reguly())

    ctx["review"] = review
    ctx["ai_qualify_status"] = ai_status
    ctx["liczba_regul"] = liczba_regul
    ctx["active_tab"] = "review"

    return templates.TemplateResponse(request=request, name="pages/review.html", context=ctx)


@router.post("/api/costs/ai-qualify-run", response_class=HTMLResponse)
async def run_ai_cost_qualification(request: Request):
    """
    Uruchamia kwalifikację faktur AI w tle z analizą zasadności gospodarczej
    oraz poradami certyfikowanego księgowego.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    from src.web.services.ai_cost_qualifier import AICostQualifierService

    await AICostQualifierService.start_ai_qualification(profile, rok, miesiac)

    status_info = AICostQualifierService.get_status(profile.nip, rok, miesiac)
    status_ctx = {
        "request": request,
        "status": status_info,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(request=request, name="partials/ai_qualify_banner.html", context=status_ctx)


@router.get("/api/costs/ai-qualify-status", response_class=HTMLResponse)
async def get_ai_cost_qualification_status(request: Request):
    """Endpoint pollingu stanu kwalifikacji faktur AI w tle."""
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        return HTMLResponse("")

    from src.web.services.ai_cost_qualifier import AICostQualifierService

    status_info = AICostQualifierService.get_status(profile.nip, rok, miesiac)

    headers = {}
    if status_info.get("status") == "completed":
        headers["HX-Trigger"] = "refresh-review-tables"

    status_ctx = {
        "request": request,
        "status": status_info,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/ai_qualify_banner.html",
        context=status_ctx,
        headers=headers,
    )


@router.post("/api/costs/approve", response_class=HTMLResponse)
async def approve_cost_invoice(
    request: Request,
    numer: str = Query(...),
    lp: int = Query(...),
    kwalifikacja: Optional[str] = Form(None),
):
    """
    Zatwierdzenie kwalifikacji faktury kosztowej:
    - Zapisuje decyzję w ReczneKwalifikacjeService dla bieżącego okresu
    - Oznacza w AICostQualifierService jako zatwierdzone (BEZ tworzenia trwałej reguły)
    - Odświeża wiersz tabeli z normalnym tłem (przycisk 'Zatwierdź' znika)
    """
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    # Kwalifikacja może przyjść z Form lub z Query
    effective_kwal = kwalifikacja or request.query_params.get("kwalifikacja")

    from src.web.services.ai_cost_qualifier import AICostQualifierService

    faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
    inv = next((i for i in faktury if i.numer in (numer, cleaned_numer) or i.numer.strip() == cleaned_numer), None)

    sugestie = AICostQualifierService.load_suggestions(profile, rok, miesiac)
    reczne_overrides = ReczneKwalifikacjeService.load_overrides(profile, rok, miesiac)

    if inv and inv.pozycje:
        for p in inv.pozycje:
            norm_desc = CostClassifier.normalize_desc(p.opis)
            key_norm = f"{inv.numer.strip()}::{norm_desc}"
            key_lower = f"{inv.numer.strip()}::{p.opis.strip().lower()}"

            item_ov = (
                reczne_overrides.get(key_norm) or reczne_overrides.get(key_lower) or reczne_overrides.get(cleaned_numer)
            )
            sug = sugestie.get(key_lower) or sugestie.get(key_norm)

            target_kwal = (
                effective_kwal
                or (item_ov["kwalifikacja"] if item_ov and item_ov.get("kwalifikacja") else None)
                or (sug.kwalifikacja_sugerowana if sug and sug.kwalifikacja_sugerowana else None)
                or "FIRMOWY_100"
            )
            if target_kwal not in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
                target_kwal = "FIRMOWY_100"

            # 1. Zapis ręcznej decyzji dla okresu
            ReczneKwalifikacjeService.save_override(
                profile=profile,
                rok=rok,
                miesiac=miesiac,
                numer_faktury=inv.numer,
                kwalifikacja=KwalifikacjaKosztu(target_kwal),
                opis_pozycji=p.opis,
            )

            # 2. Oznaczenie w sugestiach AI jako zatwierdzone (BEZ dodawania reguły)
            AICostQualifierService.approve_item(
                profile=profile,
                rok=rok,
                miesiac=miesiac,
                numer_faktury=inv.numer,
                pozycja_opis=p.opis,
                kwalifikacja=target_kwal,
                save_as_rule=False,
            )
    else:
        item_ov = reczne_overrides.get(cleaned_numer)
        sug = sugestie.get(cleaned_numer) or sugestie.get(f"{cleaned_numer}::{cleaned_numer.lower()}")
        target_kwal = (
            effective_kwal
            or (item_ov["kwalifikacja"] if item_ov and item_ov.get("kwalifikacja") else None)
            or (sug.kwalifikacja_sugerowana if sug and sug.kwalifikacja_sugerowana else None)
            or "FIRMOWY_100"
        )
        if target_kwal not in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
            target_kwal = "FIRMOWY_100"

        # 1. Zapis ręcznej decyzji dla okresu
        ReczneKwalifikacjeService.save_override(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=inv.numer if inv else cleaned_numer,
            kwalifikacja=KwalifikacjaKosztu(target_kwal),
            opis_pozycji=None,
        )

        # 2. Oznaczenie w sugestiach AI jako zatwierdzone (BEZ dodawania reguły)
        AICostQualifierService.approve_item(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=inv.numer if inv else cleaned_numer,
            pozycja_opis=cleaned_numer,
            kwalifikacja=target_kwal,
            save_as_rule=False,
        )

    review = PreSettlementReview.build(profile, rok, miesiac)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)
    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-row-{lp}" class="expense-row text-xs text-slate-500 p-2">Zatwierdzono fakturę {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary"},
    )


@router.post("/api/costs/approve-item", response_class=HTMLResponse)
async def approve_single_item(
    request: Request,
    numer: str = Query(...),
    item_idx: int = Query(...),
    lp: int = Query(...),
    rok: Optional[str] = Query(None),
    miesiac: Optional[str] = Query(None),
    kwalifikacja: Optional[str] = Form(None),
    opis: Optional[str] = Form(None),
    sprzedawca_nip: Optional[str] = Form(None),
):
    """Zatwierdza pojedynczą pozycję w fakturze wielopozycyjnej."""
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    effective_rok = rok or request.query_params.get("rok") or ctx["rok"]
    effective_miesiac = miesiac or request.query_params.get("miesiac") or ctx["miesiac"]
    if len(effective_miesiac) == 1:
        effective_miesiac = f"0{effective_miesiac}"
    rok = effective_rok
    miesiac = effective_miesiac

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    effective_kwal = kwalifikacja or request.query_params.get("kwalifikacja")
    effective_opis = opis or request.query_params.get("opis")

    from src.web.services.ai_cost_qualifier import AICostQualifierService

    faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
    inv = next((i for i in faktury if i.numer in (numer, cleaned_numer) or i.numer.strip() == cleaned_numer), None)

    pos_opis = effective_opis
    if not pos_opis and inv and inv.pozycje and item_idx < len(inv.pozycje):
        pos_opis = inv.pozycje[item_idx].opis

    reczne_overrides = ReczneKwalifikacjeService.load_overrides(profile, rok, miesiac)
    sugestie = AICostQualifierService.load_suggestions(profile, rok, miesiac)

    target_kwal = effective_kwal
    if not target_kwal and pos_opis:
        norm_desc = CostClassifier.normalize_desc(pos_opis)
        key_norm = f"{cleaned_numer}::{norm_desc}"
        key_lower = f"{cleaned_numer}::{pos_opis.strip().lower()}"

        item_ov = (
            reczne_overrides.get(key_norm) or reczne_overrides.get(key_lower) or reczne_overrides.get(cleaned_numer)
        )
        sug = sugestie.get(key_lower) or sugestie.get(key_norm)

        if item_ov and item_ov.get("kwalifikacja"):
            target_kwal = item_ov["kwalifikacja"]
        elif sug and sug.kwalifikacja_sugerowana:
            target_kwal = sug.kwalifikacja_sugerowana

    if not target_kwal and inv and inv.pozycje and item_idx < len(inv.pozycje):
        reguly_firmy = RegulyKosztoweFirmy.load(profile)
        res_audit = CostClassifier.classify_item(
            inv.pozycje[item_idx],
            inv.sprzedawca.nip if (inv.sprzedawca and inv.sprzedawca.nip) else "",
            reguly_firmy,
            kody_pkd=profile.kody_pkd,
        )
        if res_audit.kwalifikacja != KwalifikacjaKosztu.DO_WYJASNIENIA:
            target_kwal = res_audit.kwalifikacja.value

    if target_kwal not in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
        target_kwal = "FIRMOWY_100"

    if pos_opis:
        # 1. Zapis decyzji w ReczneKwalifikacjeService dla bieżącego okresu
        ReczneKwalifikacjeService.save_override(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=inv.numer if inv else cleaned_numer,
            kwalifikacja=KwalifikacjaKosztu(target_kwal),
            opis_pozycji=pos_opis,
        )

        # 2. Oznaczenie pozycji w pamięci sugestii AI (BEZ tworzenia trwałej reguły)
        AICostQualifierService.approve_item(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=inv.numer if inv else cleaned_numer,
            pozycja_opis=pos_opis,
            kwalifikacja=target_kwal,
            save_as_rule=False,
        )

    review = PreSettlementReview.build(profile, rok, miesiac)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)
    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-block-{lp}" class="expense-block text-xs text-slate-500 p-2">Zatwierdzono pozycję faktury {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary"},
    )


@router.post("/api/costs/audit-run", response_class=HTMLResponse)
async def run_intelligent_audit(request: Request):
    """
    Uruchamia ekstrakcję i audyt wstępny.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    logger.info("Uruchamianie procedury audytu dla %s za %s-%s", profile.nazwa, rok, miesiac)

    # 1. Sprawdzenie poprawności folderów i ekstrakcja (Auto-Routing)
    NonKSeFExtractor.extract_all(profile, rok, miesiac)

    # 2. Przebudowanie przeglądu
    review = PreSettlementReview.build(profile, rok, miesiac)

    # 3. Analiza statystyk audytu
    liczba_sprzedaz = len(review.sprzedaz)
    liczba_koszt = len(review.koszty)
    liczba_relokacji = len(review.relokacje)
    wykluczone_pozycje = []
    wymagajace_decyzji = []

    for k in review.koszty:
        for p in k.pozycje:
            if p.get("kwalifikacja") == "PRYWATNY_0":
                wykluczone_pozycje.append(
                    {
                        "faktura": k.numer,
                        "sprzedawca": k.sprzedawca_nazwa,
                        "opis": p.get("opis"),
                        "netto": p.get("wartosc_netto"),
                        "uzasadnienie": p.get("uzasadnienie"),
                    }
                )
            elif p.get("kwalifikacja") == "DO_WYJASNIENIA":
                wymagajace_decyzji.append(
                    {
                        "faktura": k.numer,
                        "sprzedawca": k.sprzedawca_nazwa,
                        "opis": p.get("opis"),
                    }
                )

    banner_ctx = {
        "request": request,
        "profile": profile,
        "rok": rok,
        "miesiac": miesiac,
        "liczba_sprzedaz": liczba_sprzedaz,
        "liczba_koszt": liczba_koszt,
        "liczba_relokacji": liczba_relokacji,
        "wykluczone_pozycje": wykluczone_pozycje,
        "wymagajace_decyzji": wymagajace_decyzji,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/audit_result_banner.html",
        context=banner_ctx,
        headers={"HX-Trigger": "refresh-review-tables"},
    )


@router.post("/api/costs/qualify-item", response_class=HTMLResponse)
async def qualify_single_position(
    request: Request,
    numer: str = Query(...),
    item_idx: int = Query(...),
    lp: int = Query(...),
    kwalifikacja: str = Form(...),
    opis: Optional[str] = Form(None),
    sprzedawca_nip: Optional[str] = Form(None),
    zapisz_regule: bool = Form(False),
):
    """
    Zmiana kwalifikacji konkretnej pozycji w fakturze.
    Domyślnie zapisuje wyłącznie miesięczny override (ReczneKwalifikacjeService)
    dla bieżącego okresu. Reguła trwała dodawana jest tylko gdy zapisz_regule=True.
    """
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    # 1. Zapis decyzji ręcznej dla bieżącego okresu rozliczeniowego
    ReczneKwalifikacjeService.save_override(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        numer_faktury=cleaned_numer,
        kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
        opis_pozycji=opis,
    )
    logger.info(
        "Zapisano ręczną kwalifikację pozycji '%s' faktury %s -> %s (okres %s-%s)",
        opis,
        cleaned_numer,
        kwalifikacja,
        rok,
        miesiac,
    )

    # 1b. Aktualizacja w pamięci sugestii AI bez tworzenia trwałej reguły
    if opis:
        from src.web.services.ai_cost_qualifier import AICostQualifierService

        AICostQualifierService.approve_item(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=cleaned_numer,
            pozycja_opis=opis,
            kwalifikacja=kwalifikacja,
            save_as_rule=False,
        )

    # 2. Stała reguła tworzona jest wyłącznie, jeśli użytkownik kliknął dedykowany przycisk zapisu reguły
    if zapisz_regule and opis and opis.strip():
        reguly = RegulyKosztoweFirmy.load(profile)
        reguly.dodaj_regule(
            profile=profile,
            wzorzec=opis.strip(),
            kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
            uzasadnienie="Decyzja przedsiębiorcy w podglądzie pozycji faktury",
            nip_kontrahenta=sprzedawca_nip.strip() if sprzedawca_nip else None,
        )
        logger.info(
            "Utrwalono regułę dla pozycji '%s' -> %s (kontrahent NIP: %s)",
            opis.strip(),
            kwalifikacja,
            sprzedawca_nip,
        )

    # Przebudowanie przeglądu
    review = PreSettlementReview.build(profile, rok, miesiac)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)
    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-block-{lp}" class="expense-block text-xs text-slate-500 p-2">Zaktualizowano kwalifikację pozycji faktury {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary"},
    )


@router.post("/api/costs/qualify-all-items", response_class=HTMLResponse)
async def qualify_all_positions_bulk(
    request: Request,
    numer: str = Query(...),
    lp: int = Query(...),
    kwalifikacja: Optional[str] = Query(None),
):
    """
    Zbiorcza zmiana kwalifikacji wszystkich pozycji w fakturze wielopozycyjnej.
    Dostępna gdy faktura ma > 5 pozycji, pozwalając jednym kliknięciem ustawić
    100% Firmowy, 50% Samochód lub 0% Prywatny dla wszystkich pozycji.
    """
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    content_type = request.headers.get("content-type", "")
    form_data = (
        await request.form()
        if content_type.startswith("application/x-www-form-urlencoded")
        or content_type.startswith("multipart/form-data")
        else {}
    )
    effective_kwal = kwalifikacja or form_data.get("kwalifikacja") or request.query_params.get("kwalifikacja")

    if effective_kwal not in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
        raise HTTPException(status_code=400, detail=f"Nieprawidłowa kwalifikacja: {effective_kwal}")

    # 1. Pobierz fakturę i jej pozycje
    faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
    inv = next((i for i in faktury if i.numer in (numer, cleaned_numer) or i.numer.strip() == cleaned_numer), None)

    opisy = [p.opis for p in inv.pozycje] if inv and inv.pozycje else []

    # 2. Zapisz zbiorczo decyzje ręczne w ReczneKwalifikacjeService
    ReczneKwalifikacjeService.save_bulk_overrides(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        numer_faktury=inv.numer if inv else cleaned_numer,
        kwalifikacja=KwalifikacjaKosztu(effective_kwal),
        opisy_pozycji=opisy,
    )
    logger.info(
        "Zapisano zbiorczą kwalifikację faktury %s (%d pozycji) -> %s (okres %s-%s)",
        cleaned_numer,
        len(opisy),
        effective_kwal,
        rok,
        miesiac,
    )

    # 3. Zaktualizuj sugestie AI w pamięci
    if opisy:
        from src.web.services.ai_cost_qualifier import AICostQualifierService

        AICostQualifierService.approve_bulk_items(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=inv.numer if inv else cleaned_numer,
            pozycje_opisy=opisy,
            kwalifikacja=effective_kwal,
        )

    # 4. Przebudowanie przeglądu i ponowne wyrenderowanie wiersza
    review = PreSettlementReview.build(profile, rok, miesiac)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)
    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-block-{lp}" class="expense-block text-xs text-slate-500 p-2">Zatwierdzono pozycję faktury {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
        "rok": rok,
        "miesiac": miesiac,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary"},
    )


@router.get("/api/invoices/preview", response_class=HTMLResponse)
async def invoice_preview_modal(
    request: Request,
    numer: str = Query(...),
    typ: str = Query("koszty"),
):
    """
    Zwraca modal z uproszczonym podglądem faktury (pozycje, kwoty, strony)
    oraz surowym formatem JSON / XML z KSeF i ścieżką do pliku źródłowego.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    inv_type = InvoiceType.SPRZEDAZ if typ.lower() in ("sprzedaz", "sprzedaż") else InvoiceType.KOSZT
    invoices = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=inv_type)

    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    target_invoice = next(
        (inv for inv in invoices if inv.numer in (numer, cleaned_numer) or inv.numer.strip() == cleaned_numer), None
    )

    # Fallback na wypadek gdyby typ nie został precyzyjnie przekazany
    if not target_invoice:
        other_type = InvoiceType.KOSZT if inv_type == InvoiceType.SPRZEDAZ else InvoiceType.SPRZEDAZ
        other_invoices = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=other_type)
        target_invoice = next(
            (
                inv
                for inv in other_invoices
                if inv.numer in (numer, cleaned_numer) or inv.numer.strip() == cleaned_numer
            ),
            None,
        )
        if target_invoice:
            inv_type = other_type

    if not target_invoice:
        raise HTTPException(status_code=404, detail=f"Nie znaleziono faktury: {numer}")

    raw_json = json.dumps(target_invoice.to_dict(), indent=2, ensure_ascii=False, default=str)
    raw_xml = target_invoice.raw_xml

    file_path = getattr(target_invoice, "plik_zrodlowy", None)

    # Jeśli brak pliku źródłowego, przeszukaj katalogi ksef oraz non-ksef-extracted
    if not file_path:
        for subfolder in ["ksef", "non-ksef-extracted", "non-ksef-raw"]:
            dir_path = InvoiceStorage.get_invoice_dir(profile, rok, miesiac, typ=inv_type) / subfolder
            if dir_path.exists():
                for f in dir_path.glob("*"):
                    if f.is_file() and not f.name.endswith(".PRZENIESIONO.txt"):
                        if f.suffix == ".json":
                            try:
                                data = json.loads(f.read_text(encoding="utf-8"))
                                if data.get("numer") == numer:
                                    file_path = str(f)
                                    break
                            except Exception:
                                pass
                        elif f.suffix == ".xml" and numer.replace("/", "_") in f.name:
                            file_path = str(f)
                            break
            if file_path:
                break

    # Jeśli brak w pamięci XML, poszukaj pliku XML obok pliku źródłowego
    if not raw_xml and file_path:
        src_path = Path(file_path)
        xml_candidate = src_path.with_suffix(".xml")
        if xml_candidate.exists():
            try:
                raw_xml = xml_candidate.read_text(encoding="utf-8")
            except Exception:
                pass

    modal_ctx = {
        "request": request,
        "invoice": target_invoice,
        "typ": inv_type.value,
        "raw_json": raw_json,
        "raw_xml": raw_xml,
        "plik_zrodlowy": file_path,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/invoice_preview_modal.html",
        context=modal_ctx,
        headers={"HX-Trigger": "open-invoice-modal"},
    )


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
    Domyślnie zapisuje wyłącznie miesięczny override (ReczneKwalifikacjeService)
    dla bieżącego okresu. Reguła trwała dodawana jest tylko gdy zapisz_regule=True.
    """
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    # 1. Zapis decyzji ręcznej dla bieżącego okresu rozliczeniowego
    faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
    inv = next((i for i in faktury if i.numer in (numer, cleaned_numer) or i.numer.strip() == cleaned_numer), None)

    ReczneKwalifikacjeService.save_override(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        numer_faktury=cleaned_numer,
        kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
        opis_pozycji=None,
    )
    if inv and len(inv.pozycje) == 1:
        ReczneKwalifikacjeService.save_override(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=cleaned_numer,
            kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
            opis_pozycji=inv.pozycje[0].opis,
        )
    logger.info(
        "Zapisano ręczną kwalifikację faktury %s -> %s (okres %s-%s)",
        cleaned_numer,
        kwalifikacja,
        rok,
        miesiac,
    )

    # 1b. Aktualizacja w pamięci sugestii AI bez tworzenia trwałej reguły
    from src.web.services.ai_cost_qualifier import AICostQualifierService

    if inv and inv.pozycje:
        for p in inv.pozycje:
            AICostQualifierService.approve_item(
                profile=profile,
                rok=rok,
                miesiac=miesiac,
                numer_faktury=cleaned_numer,
                pozycja_opis=p.opis,
                kwalifikacja=kwalifikacja,
                save_as_rule=False,
            )
    else:
        AICostQualifierService.approve_item(
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            numer_faktury=cleaned_numer,
            pozycja_opis=cleaned_numer,
            kwalifikacja=kwalifikacja,
            save_as_rule=False,
        )

    # 2. Stała reguła tworzona jest wyłącznie, jeśli użytkownik zażądał zapisu stałej reguły
    if zapisz_regule:
        reguly = RegulyKosztoweFirmy.load(profile)
        inv = next((i for i in faktury if i.numer in (numer, cleaned_numer) or i.numer.strip() == cleaned_numer), None)
        seller_nip = inv.sprzedawca.nip if inv and inv.sprzedawca else sprzedawca_nip
        if inv and len(inv.pozycje) == 1:
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=inv.pozycje[0].opis.strip(),
                kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
                uzasadnienie="Kwalifikacja zaktualizowana przez przedsiębiorcę w UI",
                nip_kontrahenta=seller_nip,
            )
        elif opis and opis.strip():
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=opis.strip(),
                kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
                uzasadnienie="Kwalifikacja zaktualizowana przez przedsiębiorcę w UI",
                nip_kontrahenta=seller_nip,
            )
        else:
            wzorzec = inv.numer if inv else cleaned_numer
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=wzorzec,
                kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
                uzasadnienie="Kwalifikacja zaktualizowana przez przedsiębiorcę w UI",
                nip_kontrahenta=seller_nip,
            )

    # Przebudowanie przeglądu dla spójnych danych
    review = PreSettlementReview.build(profile, rok, miesiac)

    # Znalezienie konkretnego wydatku po numerze (dokładnym lub odkodowanym)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)

    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-row-{lp}" class="expense-row text-xs text-slate-500 p-2">Zaktualizowano kwalifikację <span class="font-semibold">{kwalifikacja}</span> dla faktury {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
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


@router.post("/api/rules/save-from-item", response_class=HTMLResponse)
async def save_rule_from_item(
    request: Request,
    numer: str = Form(...),
    lp: int = Form(...),
    kwalifikacja: str = Form(...),
    opis: Optional[str] = Form(None),
    sprzedawca_nip: Optional[str] = Form(None),
    uzasadnienie: Optional[str] = Form(None),
):
    """
    Dedykowane dodawanie stałej reguły z przycisku obok selektora kwalifikacji.
    Utrwala regułę w reguly_kosztowe.json oraz odświeża wiersz tabeli.
    """
    import urllib.parse

    cleaned_numer = urllib.parse.unquote(numer).strip()
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak aktywnego profilu firmy")

    wzorzec = opis.strip() if (opis and opis.strip()) else cleaned_numer
    seller_nip = sprzedawca_nip.strip() if sprzedawca_nip else None

    # Zapis reguły stałej w profilu firmy
    reguly = RegulyKosztoweFirmy.load(profile)
    reguly.dodaj_regule(
        profile=profile,
        wzorzec=wzorzec,
        kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
        uzasadnienie=uzasadnienie.strip() if uzasadnienie else "Utrwalono regułę z tabeli przeglądu kosztów",
        nip_kontrahenta=seller_nip,
    )

    # Zapis również jako override bieżącego miesiąca
    ReczneKwalifikacjeService.save_override(
        profile=profile,
        rok=rok,
        miesiac=miesiac,
        numer_faktury=cleaned_numer,
        kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
        opis_pozycji=opis,
    )

    review = PreSettlementReview.build(profile, rok, miesiac)
    target_item = next(
        (item for item in review.koszty if item.numer in (numer, cleaned_numer) or item.numer.strip() == cleaned_numer),
        None,
    )
    if not target_item:
        target_item = next((item for item in review.koszty if item.lp == lp), None)
    if not target_item and review.koszty:
        target_item = review.koszty[0]

    if not target_item:
        return HTMLResponse(
            content=f'<div id="expense-block-{lp}" class="expense-block text-xs text-slate-500 p-2">Zatwierdzono pozycję faktury {cleaned_numer}</div>',
            headers={"HX-Trigger": "update-costs-summary"},
        )

    row_ctx = {
        "request": request,
        "item": target_item,
        "profile": profile,
        "review": review,
        "include_summary_oob": True,
        "rok": rok,
        "miesiac": miesiac,
        "regula_zapisana_msg": f"Zapisano stałą regułę dla '{wzorzec}'",
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/expense_row.html",
        context=row_ctx,
        headers={"HX-Trigger": "update-costs-summary, rules-updated"},
    )


@router.get("/api/rules/list", response_class=HTMLResponse)
async def list_company_rules(request: Request):
    """
    Zwraca listę wszystkich reguł kosztowych firmy (kontrahentów i globalnych).
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    reguly = RegulyKosztoweFirmy.load(profile)
    wszystkie = reguly.pobierz_wszystkie_reguly()
    return templates.TemplateResponse(
        request=request,
        name="partials/rules_list.html",
        context={
            "request": request,
            "profile": profile,
            "reguly": wszystkie,
            "liczba_regul": len(wszystkie),
        },
    )


@router.post("/api/rules/delete", response_class=HTMLResponse)
async def delete_company_rule(
    request: Request,
    wzorzec: str = Form(...),
    sprzedawca_nip: Optional[str] = Form(None),
):
    """
    Usuwa regułę kosztową z pliku reguly_kosztowe.json i zwraca odświeżoną listę reguł.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    reguly = RegulyKosztoweFirmy.load(profile)
    reguly.usun_regule(
        profile=profile,
        wzorzec=wzorzec,
        nip_kontrahenta=sprzedawca_nip.strip() if (sprzedawca_nip and sprzedawca_nip.strip()) else None,
    )
    wszystkie = reguly.pobierz_wszystkie_reguly()
    return templates.TemplateResponse(
        request=request,
        name="partials/rules_list.html",
        context={
            "request": request,
            "profile": profile,
            "reguly": wszystkie,
            "liczba_regul": len(wszystkie),
            "komunikat": f"Usunięto regułę: '{wzorzec}'",
        },
        headers={"HX-Trigger": "refresh-review-tables, update-costs-summary, rules-updated"},
    )


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
        """,
        headers={"HX-Trigger": "refresh-review-tables, update-costs-summary, rules-updated"},
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
