"""
src/web/routers/companies.py
Obsługa przełączania firm, okresów rozliczeniowych oraz dodawania nowej firmy (onboarding).
"""

import re
from typing import Optional

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.core.company import initialize_company
from src.level_1_ingestion.company_fetcher import CompanyFetcher
from src.web.config import COOKIE_ACTIVE_MONTH, COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR, TEMPLATES_DIR
from src.web.dependencies import get_global_context

router = APIRouter(prefix="/firmy", tags=["Firmy"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.post("/switch")
async def switch_company(
    response: Response,
    request: Request,
    nip: str = Form(...),
    redirect_url: str = Form("/"),
):
    """
    Zmienia aktywną firmę zapisując ciasteczko sesyjne i przekierowuje na wybraną stronę.
    """
    if nip == "__NEW__":
        return RedirectResponse(url="/firmy/nowa", status_code=303)

    resp = RedirectResponse(url=redirect_url, status_code=303)
    resp.set_cookie(key=COOKIE_ACTIVE_NIP, value=nip, max_age=30 * 86400, httponly=True)
    return resp


@router.post("/period")
async def switch_period(
    response: Response,
    request: Request,
    rok: str = Form(...),
    miesiac: str = Form(...),
    redirect_url: str = Form("/"),
):
    """
    Zmienia aktywny okres rozliczeniowy (rok i miesiąc) w ciasteczkach.
    """
    if len(miesiac) == 1:
        miesiac = f"0{miesiac}"
    resp = RedirectResponse(url=redirect_url, status_code=303)
    resp.set_cookie(key=COOKIE_ACTIVE_YEAR, value=rok, max_age=30 * 86400, httponly=True)
    resp.set_cookie(key=COOKIE_ACTIVE_MONTH, value=miesiac, max_age=30 * 86400, httponly=True)
    return resp


@router.get("/nowa", response_class=HTMLResponse)
async def new_company_view(request: Request):
    """
    Ekran dodawania nowej firmy do księgowania w TaxPilot AI.
    """
    ctx = get_global_context(request)
    ctx.update(
        {
            "error_message": None,
            "success_message": None,
            "form_data": {
                "nip": "",
                "nazwa": "",
                "adres": "",
                "regon": "",
                "forma_opodatkowania": "RYCZALT",
                "domyslna_stawka_ryczaltu": "0.12",
                "platnik_vat": True,
                "zus_typ": "PELNY_ZUS",
                "chorobowe_dobrowolne": True,
                "kody_pkd": "62.01.Z, 62.02.Z",
                "srodowisko_ksef": "PROD",
                "token_ksef": "",
                "auto_fetch": True,
            },
        }
    )
    return templates.TemplateResponse(request=request, name="pages/new_company.html", context=ctx)


@router.post("/nowa", response_class=HTMLResponse)
async def create_new_company_handler(
    request: Request,
    nip: str = Form(...),
    nazwa: Optional[str] = Form(None),
    adres: Optional[str] = Form(None),
    regon: Optional[str] = Form(None),
    forma_opodatkowania: str = Form("RYCZALT"),
    domyslna_stawka_ryczaltu: str = Form("0.12"),
    platnik_vat: Optional[str] = Form(None),
    zus_typ: str = Form("PELNY_ZUS"),
    chorobowe_dobrowolne: Optional[str] = Form(None),
    kody_pkd: Optional[str] = Form(None),
    srodowisko_ksef: str = Form("PROD"),
    token_ksef: Optional[str] = Form(None),
    auto_fetch: Optional[str] = Form(None),
):
    """
    Obsługuje formularz utworzenia nowej firmy. Po utworzeniu ustawia ciasteczko
    z nowym NIP i przekierowuje na ekran główny.
    """
    clean_nip = re.sub(r"[^0-9]", "", nip or "")
    is_vat = platnik_vat in ("on", "true", "1", "True")
    is_chorobowe = chorobowe_dobrowolne in ("on", "true", "1", "True")
    should_auto_fetch = auto_fetch in ("on", "true", "1", "True")

    form_dict = {
        "nip": clean_nip or nip,
        "nazwa": nazwa or "",
        "adres": adres or "",
        "regon": regon or "",
        "forma_opodatkowania": forma_opodatkowania,
        "domyslna_stawka_ryczaltu": domyslna_stawka_ryczaltu,
        "platnik_vat": is_vat,
        "zus_typ": zus_typ,
        "chorobowe_dobrowolne": is_chorobowe,
        "kody_pkd": kody_pkd or "",
        "srodowisko_ksef": srodowisko_ksef,
        "token_ksef": token_ksef or "",
        "auto_fetch": should_auto_fetch,
    }

    if len(clean_nip) != 10:
        ctx = get_global_context(request)
        ctx.update(
            {
                "error_message": f"Nieprawidłowy NIP ({nip}). Numer NIP musi składać się dokładnie z 10 cyfr.",
                "form_data": form_dict,
            }
        )
        return templates.TemplateResponse(request=request, name="pages/new_company.html", context=ctx, status_code=400)

    try:
        stawka_float = float(domyslna_stawka_ryczaltu)
    except ValueError:
        stawka_float = 0.12

    pkd_list = [p.strip().upper() for p in (kody_pkd or "").split(",") if p.strip()]

    try:
        profile = initialize_company(
            nip=clean_nip,
            nazwa=nazwa,
            adres=adres,
            regon=regon,
            forma_opodatkowania=forma_opodatkowania,
            domyslna_stawka_ryczaltu=stawka_float,
            platnik_vat=is_vat,
            zus_typ=zus_typ,
            chorobowe_dobrowolne=is_chorobowe,
            kody_pkd=pkd_list,
            srodowisko_ksef=srodowisko_ksef,
            token_ksef=token_ksef,
            auto_fetch=should_auto_fetch,
        )
    except ValueError as e:
        ctx = get_global_context(request)
        ctx.update(
            {
                "error_message": str(e),
                "form_data": form_dict,
            }
        )
        return templates.TemplateResponse(request=request, name="pages/new_company.html", context=ctx, status_code=400)
    except Exception as e:
        ctx = get_global_context(request)
        ctx.update(
            {
                "error_message": f"Błąd tworzenia profilu firmy: {str(e)}",
                "form_data": form_dict,
            }
        )
        return templates.TemplateResponse(request=request, name="pages/new_company.html", context=ctx, status_code=500)

    # Sukces – przekierowanie na pulpit z ciasteczkiem nowo dodanej firmy
    resp = RedirectResponse(url="/?nowa_firma=1", status_code=303)
    resp.set_cookie(key=COOKIE_ACTIVE_NIP, value=profile.nip, max_age=30 * 86400, httponly=True)
    return resp


@router.post("/lookup-nip")
@router.get("/lookup-nip")
async def lookup_company_nip_endpoint(request: Request):
    """
    Endpoint API do odpytywania rejestrów publicznych (Biała Lista MF / CEIDG)
    dla formularza nowej firmy.
    """
    raw_nip = ""
    if request.method == "POST":
        try:
            body = await request.form()
            nip_val = body.get("nip", "")
            raw_nip = str(nip_val) if nip_val is not None else ""
        except Exception:
            pass
    if not raw_nip:
        raw_nip = request.query_params.get("nip", "")

    clean_nip = re.sub(r"[^0-9]", "", str(raw_nip))
    if len(clean_nip) != 10:
        return JSONResponse({"success": False, "error": "Podaj poprawny 10-cyfrowy NIP", "data": None}, status_code=400)

    try:
        data = CompanyFetcher.fetch_company_info(clean_nip)
        kody = data.get("kody_pkd") or []
        return JSONResponse(
            {
                "success": True,
                "error": None,
                "data": {
                    "nip": clean_nip,
                    "nazwa": data.get("nazwa") or "",
                    "adres": data.get("adres") or "",
                    "regon": data.get("regon") or "",
                    "platnik_vat": bool(data.get("platnik_vat", True)),
                    "kody_pkd": ", ".join(kody),
                    "status_vat": "Czynny podatnik VAT" if data.get("platnik_vat") else "Zwolniony z VAT",
                    "zrodlo": data.get("zrodlo") or "Biała Lista MF",
                },
            }
        )
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": f"Błąd pobierania danych z rejestru: {str(e)}", "data": None}, status_code=500
        )
