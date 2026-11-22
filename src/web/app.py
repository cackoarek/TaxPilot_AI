"""
src/web/app.py
Główna aplikacja FastAPI dla TaxPilot AI (Wariant B: Server-Driven UI).
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.logging_config import get_logger, setup_logging
from src.web.config import (
    COOKIE_AUTH_TOKEN,
    DEBUG,
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATIC_DIR,
    TAXPILOT_ACCESS_TOKEN,
)
from src.web.routers import advisor, aml, bookkeeping, companies, copilot, dashboard, invoices, settings, settlement

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
    Opcjonalna autoryzacja tokenem (NET-1, SEC-3).
    Jeśli zmienna TAXPILOT_ACCESS_TOKEN jest pusta -> tryb lokalny bez hasła.
    Jeśli jest ustawiona -> wymaga poprawnego tokenu w nagłówku, ciasteczku lub query (?token=).
    Stosuje stałoczasowe porównywanie (secrets.compare_digest) oraz automatycznie usuwa token
    z URL (Redirect 303), zapobiegając jego wyciekowi do historii i logów przeglądarki.
    """
    import os
    import secrets

    # Sprawdzaj dynamicznie ze środowiska (np. dla testów z os.environ)
    required_token = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip() or TAXPILOT_ACCESS_TOKEN
    if not required_token:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/static") or path in ("/health", "/favicon.ico", "/login", "/logout"):
        return await call_next(request)

    # 1. Obsługa parametru query ?token=...
    query_token = request.query_params.get("token")
    if query_token:
        if secrets.compare_digest(query_token, required_token):
            # Ustaw bezpieczne ciasteczko i natychmiast przekieruj (303) na czysty URL bez parametru token
            clean_url = str(request.url.remove_query_params("token"))
            response = RedirectResponse(url=clean_url, status_code=303)
            response.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                samesite="lax",
            )
            return response
        else:
            return JSONResponse(
                status_code=401,
                content={"detail": "Wymagana autoryzacja: niepoprawny token w parametrze query"},
            )

    # 2. Sprawdź nagłówek Authorization (Bearer <token>)
    token_candidate = None
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        parts = auth_header.split()
        token_candidate = parts[-1] if parts else auth_header

    # 3. Sprawdź ciasteczko
    if not token_candidate:
        token_candidate = request.cookies.get(COOKIE_AUTH_TOKEN)

    # 4. Sprawdź nagłówek x-access-token
    if not token_candidate:
        token_candidate = request.headers.get("x-access-token")

    # 5. Stałoczasowa weryfikacja tokena
    if token_candidate and secrets.compare_digest(token_candidate, required_token):
        return await call_next(request)

    # 6. Brak lub błędny token -> 401
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
                        Wprowadź token dostępowy, aby kontynuować pracę:
                    </p>
                    <form method="POST" action="/login" class="space-y-3 pt-2">
                        <input type="password" name="token" placeholder="Wprowadź TAXPILOT_ACCESS_TOKEN" required
                               class="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <button type="submit"
                                class="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition">
                            Zaloguj i zapamiętaj sesję
                        </button>
                    </form>
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


@app.post("/login")
async def login_post(request: Request):
    """Logowanie formularzem POST z tokenem dostępowym (SEC-3)."""
    import os
    import secrets

    required_token = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip() or TAXPILOT_ACCESS_TOKEN
    form_data = await request.form()
    token_candidate = str(form_data.get("token", "")).strip()

    if not required_token or (token_candidate and secrets.compare_digest(token_candidate, required_token)):
        redirect_url = str(form_data.get("redirect_url", "/")) or "/"
        resp = RedirectResponse(url=redirect_url, status_code=303)
        if required_token:
            resp.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                samesite="lax",
            )
        return resp

    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html lang="pl">
        <head>
            <meta charset="utf-8">
            <title>Błąd Logowania - TaxPilot AI</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4 font-sans text-slate-800">
            <div class="max-w-md w-full bg-white p-6 rounded-2xl border border-red-200 shadow-sm text-center space-y-4">
                <div class="w-12 h-12 bg-red-100 text-red-700 rounded-full flex items-center justify-center mx-auto text-xl font-bold">❌</div>
                <h1 class="text-lg font-bold text-slate-900">Nieprawidłowy Token Dostępowy</h1>
                <p class="text-xs text-slate-600">Podany token nie jest zgodny z konfiguracją serwera.</p>
                <a href="/" class="inline-block py-2 px-4 bg-slate-800 text-white rounded-lg text-sm font-medium hover:bg-slate-900">Spróbuj ponownie</a>
            </div>
        </body>
        </html>
        """,
        status_code=401,
    )


@app.get("/logout")
async def logout():
    """Wylogowanie sesji autoryzacyjnej."""
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(COOKIE_AUTH_TOKEN)
    return resp


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
