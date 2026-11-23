"""
src/web/app.py
Główna aplikacja FastAPI dla TaxPilot AI (Wariant B: Server-Driven UI).
Zawiera zintegrowane mechanizmy bezpieczeństwa:
- CSRF Origin/Referer check dla Local-First (SEC-11)
- Stałoczasowe porównywanie tokena autoryzacji (SEC-3)
- Usuwanie tokena z URL (303 Redirect) do bezpiecznego ciasteczka (SEC-3)
- Dynamiczną flagę Secure dla cookies przy HTTPS (SEC-6)
- Ochronę przed atakami Brute-Force i rate limiting (SEC-7)
- Walidację wejściową tokena (SEC-8)
- Ochronę przed Open Redirect w formularzu logowania (SEC-9)
- Automatyczną migrację uprawnień chmod 700/600 (SEC-10)
"""

import asyncio
import html
import os
import secrets
import sys
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Dict, List

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.core.company import migrate_data_permissions
from src.logging_config import get_logger, setup_logging
from src.web.config import (
    COOKIE_AUTH_TOKEN,
    COOKIE_CSRF_TOKEN,
    DEBUG,
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATIC_DIR,
    TAXPILOT_ACCESS_TOKEN,
)
from src.web.routers import advisor, aml, bookkeeping, companies, copilot, dashboard, invoices, settings, settlement
from src.web.utils.security import (
    generate_csrf_token,
    is_safe_redirect_url,
    is_secure_request,
    is_trusted_origin,
    validate_csrf_token,
)

# Inicjalizacja centralnego logowania (konsola + taxpilot.log)
setup_logging()
logger = get_logger("taxpilot.web")

# Śledzenie prób logowania per IP (Rate Limiter - SEC-7)
_login_attempts: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_MAX_ATTEMPTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 60.0


def reset_login_rate_limits() -> None:
    """Czyści historię prób logowania (wykorzystywane m.in. w testach)."""
    _login_attempts.clear()


def check_login_rate_limit(client_ip: str) -> bool:
    """Sprawdza, czy dany adres IP nie przekroczył dopuszczalnego limitu prób logowania (SEC-7)."""
    now = time.time()
    attempts = _login_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    if len(attempts) >= _RATE_LIMIT_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Zarządza cyklem życia aplikacji: migracja uprawnień i walidacja sekretów."""
    # 1. Automatyczna migracja uprawnień dyskowych (SEC-10)
    try:
        updated = migrate_data_permissions()
        if updated > 0:
            logger.info("Migracja uprawnień plików i folderów zakończona (zaktualizowano: %d).", updated)
    except Exception as exc:
        logger.warning("Błąd podczas automatycznej migracji uprawnień danych: %s", exc)

    # 2. Weryfikacja jakości tokena dostępowego (SEC-8)
    token = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip() or TAXPILOT_ACCESS_TOKEN
    if token and len(token) < 32:
        logger.warning(
            "TAXPILOT_ACCESS_TOKEN ma mniej niż 32 znaki. Dla optymalnego bezpieczeństwa zalecane jest wygenerowanie losowego tokena (np. secrets.token_urlsafe(32))."
        )
    yield


app = FastAPI(
    title="TaxPilot AI",
    description="Autonomiczny Asystent Księgowo-Podatkowy JDG",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """
    Dodaje uniwersalne nagłówki bezpieczeństwa HTTP do każdej odpowiedzi (SEC-15, UI-1).
    Chroni przed atakami Clickjacking (X-Frame-Options), MIME-sniffing (X-Content-Type-Options)
    oraz wyciekiem danych w nagłówkach Referer (Referrer-Policy).
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


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
async def csrf_origin_protection_middleware(request: Request, call_next):
    """
    Ochrona przed atakami CSRF w architekturze Local-First (SEC-11, SEC-20).
    Dla metod mutujących stan (POST, PUT, DELETE, PATCH):
    1. Weryfikuje nagłówki Origin i Referer (w tym X-Forwarded-Host dla reverse proxy).
    2. Jeśli przesłano token CSRF (nagłówek X-CSRF-Token lub X-CSRFToken), weryfikuje zgodność z ciasteczkiem.
    3. Zarządza ciasteczkiem taxpilot_csrf_token dla formularzy i zapytań AJAX.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not is_trusted_origin(request):
            logger.warning(
                "CSRF: Zablokowano żądanie mutujące %s %s z niezaufanego źródła (Origin: %s, Referer: %s)",
                request.method,
                request.url.path,
                request.headers.get("origin"),
                request.headers.get("referer"),
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF: Odrzucono żądanie z niezaufanego źródła (Origin/Referer)"},
            )

        submitted_csrf = request.headers.get("x-csrf-token") or request.headers.get("x-csrftoken")
        if submitted_csrf and not validate_csrf_token(request, submitted_csrf):
            logger.warning("CSRF: Odrzucono żądanie z nieprawidłowym tokenem X-CSRF-Token dla %s", request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF: Nieprawidłowy token CSRF"},
            )

    csrf_token = request.cookies.get(COOKIE_CSRF_TOKEN)
    must_set_cookie = False
    if not csrf_token:
        csrf_token = generate_csrf_token()
        must_set_cookie = True
    request.state.csrf_token = csrf_token

    response = await call_next(request)

    if must_set_cookie:
        response.set_cookie(
            key=COOKIE_CSRF_TOKEN,
            value=csrf_token,
            httponly=False,
            secure=is_secure_request(request),
            samesite="lax",
        )
    return response


@app.middleware("http")
async def optional_token_auth_middleware(request: Request, call_next):
    """
    Opcjonalna autoryzacja tokenem (NET-1, SEC-3, SEC-6, SEC-7, SEC-8).
    Jeśli zmienna TAXPILOT_ACCESS_TOKEN jest pusta -> tryb lokalny bez hasła.
    Jeśli jest ustawiona -> wymaga poprawnego tokenu w nagłówku, ciasteczku lub query (?token=).
    Stosuje stałoczasowe porównywanie (secrets.compare_digest) oraz automatycznie usuwa token
    z URL (Redirect 303), zapobiegając jego wyciekowi do historii i logów przeglądarki.
    """
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
        if len(query_token) <= 256 and secrets.compare_digest(query_token, required_token):
            # Ustaw bezpieczne ciasteczko i natychmiast przekieruj (303) na czysty URL bez parametru token
            clean_url = str(request.url.remove_query_params("token"))
            response = RedirectResponse(url=clean_url, status_code=303)
            response.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                secure=is_secure_request(request),
                samesite="lax",
            )
            return response
        else:
            return JSONResponse(
                status_code=401,
                content={"detail": "Wymagana autoryzacja: niepoprawny token w parametrze query"},
                headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
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

    # 5. Stałoczasowa weryfikacja tokena z limitem długości (SEC-8)
    if token_candidate and len(token_candidate) <= 256 and secrets.compare_digest(token_candidate, required_token):
        return await call_next(request)

    # 6. Brak lub błędny token -> 401
    safe_redirect = request.url.path if is_safe_redirect_url(request.url.path) else "/"
    safe_redirect_escaped = html.escape(safe_redirect, quote=True)

    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            content=f"""
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
                        <input type="hidden" name="redirect_url" value="{safe_redirect_escaped}">
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
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )
    return JSONResponse(
        content={"detail": "Wymagana autoryzacja: brak lub niepoprawny TAXPILOT_ACCESS_TOKEN"},
        status_code=401,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
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
    """Logowanie formularzem POST z tokenem dostępowym (SEC-3, SEC-6, SEC-7, SEC-8, SEC-9)."""
    client_ip = request.client.host if request.client else "127.0.0.1"

    # 1. Rate limiter per IP klienta (SEC-7)
    if not check_login_rate_limit(client_ip):
        logger.warning("Przekroczono limit prób logowania z adresu IP: %s", client_ip)
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="pl">
            <head>
                <meta charset="utf-8">
                <title>429 Zbyt Wiele Prób - TaxPilot AI</title>
                <script src="https://cdn.tailwindcss.com"></script>
            </head>
            <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4 font-sans text-slate-800">
                <div class="max-w-md w-full bg-white p-6 rounded-2xl border border-amber-200 shadow-sm text-center space-y-4">
                    <div class="w-12 h-12 bg-amber-100 text-amber-700 rounded-full flex items-center justify-center mx-auto text-xl font-bold">⏳</div>
                    <h1 class="text-lg font-bold text-slate-900">Zbyt Wiele Prób Logowania</h1>
                    <p class="text-xs text-slate-600">Przekroczono limit prób uwierzytelnienia (maksymalnie 5 na minutę). Spróbuj ponownie za 60 sekund.</p>
                    <a href="/login" class="inline-block py-2 px-4 bg-slate-800 text-white rounded-lg text-sm font-medium hover:bg-slate-900">Odśwież</a>
                </div>
            </body>
            </html>
            """,
            status_code=429,
            headers={
                "Retry-After": "60",
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            },
        )

    required_token = os.getenv("TAXPILOT_ACCESS_TOKEN", "").strip() or TAXPILOT_ACCESS_TOKEN
    form_data = await request.form()
    token_candidate = str(form_data.get("token", "")).strip()

    # 2. Walidacja długości tokena (SEC-8)
    if len(token_candidate) > 256:
        token_candidate = ""

    # 3. Stałoczasowe porównywanie tokena
    is_valid = False
    if not required_token:
        is_valid = True
    elif token_candidate and secrets.compare_digest(token_candidate, required_token):
        is_valid = True

    if is_valid:
        # 4. Bezpieczna walidacja adresu przekierowania (SEC-9 Open Redirect Prevention)
        raw_redirect = str(form_data.get("redirect_url", "/")).strip()
        target_url = raw_redirect if is_safe_redirect_url(raw_redirect) else "/"
        resp = RedirectResponse(url=target_url, status_code=303)
        if required_token:
            resp.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                secure=is_secure_request(request),
                samesite="lax",
            )
        return resp

    # 5. Błędny token -> opóźnienie ochronne (anti-brute-force) i stały komunikat błędu (SEC-7)
    time.sleep(1.0)
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
                <h1 class="text-lg font-bold text-slate-900">Nieprawidłowy token dostępu</h1>
                <p class="text-xs text-slate-600">Podany token dostępu jest nieprawidłowy lub wygasł.</p>
                <a href="/" class="inline-block py-2 px-4 bg-slate-800 text-white rounded-lg text-sm font-medium hover:bg-slate-900">Spróbuj ponownie</a>
            </div>
        </body>
        </html>
        """,
        status_code=401,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/logout")
async def logout(request: Request):
    """Wylogowanie sesji autoryzacyjnej (SEC-6)."""
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(
        COOKIE_AUTH_TOKEN,
        httponly=True,
        secure=is_secure_request(request),
        samesite="lax",
    )
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
