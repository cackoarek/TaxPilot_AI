"""
src/web/app.py
Główna aplikacja FastAPI dla TaxPilot AI (Wariant B: Server-Driven UI).
"""
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.logging_config import setup_logging, get_logger
from src.web.config import (
    STATIC_DIR,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEBUG,
    TAXPILOT_ACCESS_TOKEN,
    COOKIE_AUTH_TOKEN,
)
from src.web.routers import dashboard, companies, aml, settlement, copilot, invoices, advisor, settings, bookkeeping

# Inicjalizacja centralnego logowania (konsola + taxpilot.log)
setup_logging()
logger = get_logger("taxpilot.web")

app = FastAPI(
    title="TaxPilot AI",
    description="Autonomiczny Asystent Księgowo-Podatkowy JDG",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

@app.middleware("http")
async def log_requests_and_exceptions(request: Request, call_next):
    """Middleware rejestrujący żądania oraz wyłapujący wszelkie nieobsłużone wyjątki do taxpilot.log."""
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning(
                "%s %s -> status %d",
                request.method,
                request.url.path,
                response.status_code,
            )
        return response
    except Exception as exc:
        logger.exception(
            "CRITICAL: Nieobsłużony wyjątek podczas przetwarzania %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        raise exc


@app.middleware("http")
async def optional_token_auth_middleware(request: Request, call_next):
    """
    Opcjonalna autoryzacja tokenem (NET-1).
    Jeśli zmienna TAXPILOT_ACCESS_TOKEN jest pusta -> tryb lokalny bez hasła.
    Jeśli jest ustawiona -> wymaga poprawnego tokenu w nagłówku, query (?token=) lub ciasteczku.
    """
    import os
    # Sprawdzaj dynamicznie ze środowiska (np. dla testów z os.environ)
    required_token = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip() or TAXPILOT_ACCESS_TOKEN
    if not required_token:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/static") or path == "/health" or path == "/favicon.ico":
        return await call_next(request)

    token_candidate = None
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        parts = auth_header.split()
        token_candidate = parts[-1] if parts else auth_header

    if not token_candidate:
        token_candidate = request.query_params.get("token")

    if not token_candidate:
        token_candidate = request.cookies.get(COOKIE_AUTH_TOKEN)

    if not token_candidate:
        token_candidate = request.headers.get("x-access-token")

    if token_candidate == required_token:
        response = await call_next(request)
        if request.query_params.get("token") == required_token:
            response.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                samesite="lax",
            )
        return response

    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="pl">
            <head>
                <meta charset="utf-8">
                <title>401 Wymagana Autoryzacja - TaxPilot AI</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4 font-sans text-slate-800">
                <div class="max-w-md w-full bg-white p-6 rounded-2xl border border-slate-200 shadow-sm text-center space-y-4">
                    <div class="w-12 h-12 bg-amber-100 text-amber-700 rounded-full flex items-center justify-center mx-auto text-xl font-bold">🔒</div>
                    <h1 class="text-lg font-bold text-slate-900">Wymagana Autoryzacja Dostępu</h1>
                    <p class="text-xs text-slate-600 leading-relaxed">
                        Instancja TaxPilot AI została uruchomiona w trybie chronionym zmienną <code>TAXPILOT_ACCESS_TOKEN</code>.
                        Podaj poprawny token w nagłówku <code>Authorization</code>, ciasteczku lub jako parametr adresu <code>?token=TWÓJ_TOKEN</code>.
                    </p>
                </div>
            </body>
            </html>
            """,
            status_code=401,
        )
    return JSONResponse(
        content={"detail": "Wymagana autoryzacja: brak lub niepoprawny TAXPILOT_ACCESS_TOKEN"},
        status_code=401,
    )

# Montowanie plików statycznych (CSS, JS, obrazy)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Dołączanie routerów
app.include_router(dashboard.router)
app.include_router(companies.router)
app.include_router(aml.router)
app.include_router(settlement.router)
app.include_router(bookkeeping.router)
app.include_router(copilot.router)
app.include_router(invoices.router)
app.include_router(advisor.router)
app.include_router(settings.router)


@app.get("/health")
async def health_check():
    """Prosty probe stanu serwera."""
    return {"status": "ok", "app": "TaxPilot AI", "mode": "web"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.web.app:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=DEBUG,
        reload_dirs=["src"] if DEBUG else None,
        reload_delay=1.0 if DEBUG else 0.25,
    )
