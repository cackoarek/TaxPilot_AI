"""
src/web/routers/companies.py
Obsługa przełączania firm i okresów rozliczeniowych.
"""
from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import RedirectResponse
from src.web.config import COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR, COOKIE_ACTIVE_MONTH

router = APIRouter(prefix="/firmy", tags=["Firmy"])


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
