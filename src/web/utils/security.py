"""
src/web/utils/security.py
Współdzielone mechanizmy bezpieczeństwa warstwy webowej (SEC-6, SEC-9, SEC-11, SEC-16).
Zawiera:
- is_safe_redirect_url: Ochrona przed Open Redirect (CWE-601)
- is_secure_request: Wykrywanie połączeń HTTPS / SSL proxy
- is_trusted_origin: Ochrona CSRF w architekturze Local-First
"""

import os
import urllib.parse
from typing import Optional

from fastapi import Request


def is_secure_request(request: Request) -> bool:
    """Sprawdza, czy żądanie jest szyfrowane (HTTPS), za reverse-proxy SSL lub wymuszone w env (SEC-6)."""
    if os.getenv("TAXPILOT_COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
        return True
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return False


def is_safe_redirect_url(url: str) -> bool:
    """
    Weryfikuje, czy URL jest bezpieczną ścieżką względną na tym samym hoście (CWE-601 / SEC-9, SEC-16).
    Odrzuca:
    - ścieżki zaczynające się od // (protocol-relative URLs) lub /\\
    - ścieżki zawierające obcy schemat lub netloc (http:, https:, javascript:, data:)
    - znaki kontrolne i ukośniki wsteczne (\\)
    """
    if not url:
        return False
    clean = url.strip()
    if not clean.startswith("/") or clean.startswith("//") or clean.startswith("/\\"):
        return False
    if any(c in clean for c in ("\r", "\n", "\t", "\x00", "\\")):
        return False
    try:
        parsed = urllib.parse.urlsplit(clean)
        if parsed.scheme or parsed.netloc:
            return False
        return True
    except Exception:
        return False


def generate_csrf_token() -> str:
    """Generuje kryptograficznie bezpieczny token CSRF (SEC-20)."""
    import secrets

    return secrets.token_urlsafe(32)


def is_trusted_origin(request: Request) -> bool:
    """
    Weryfikuje nagłówek Origin / Referer dla żądań mutujących stan (POST, PUT, DELETE, PATCH).
    W architekturze Local-First blokuje ataki CSRF ze złośliwych stron (SEC-11, SEC-20).
    Obsługuje nagłówki X-Forwarded-Host i X-Forwarded-Proto dla środowisk reverse proxy.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")
    fwd_host = request.headers.get("x-forwarded-host")

    # Dozwolone zaufane hosty lokalne oraz hosty proxy
    trusted_hosts = {"127.0.0.1", "localhost", "testserver"}
    for candidate in (host, fwd_host):
        if candidate:
            host_clean = candidate.split(",")[0].strip().split(":")[0].lower()
            if host_clean:
                trusted_hosts.add(host_clean)

    is_secure = is_secure_request(request)

    for header_val in (origin, referer):
        if not header_val:
            continue
        clean_val = header_val.strip().lower()
        if clean_val == "null":
            return False
        try:
            parsed = urllib.parse.urlsplit(header_val)
            header_host = (parsed.hostname or "").lower()
            if header_host and header_host not in trusted_hosts:
                return False
            # Ochrona przed protocol downgrade: żądanie HTTPS nie może pochodzić z HTTP na zewnątrz
            if is_secure and parsed.scheme == "http" and header_host not in ("127.0.0.1", "localhost", "testserver"):
                return False
        except Exception:
            return False

    return True


def validate_csrf_token(request: Request, submitted_token: Optional[str]) -> bool:
    """
    Weryfikuje poprawność tokena CSRF w schemacie Double-Submit Cookie (SEC-20).
    Porównuje przesłany token (z nagłówka X-CSRF-Token lub pola formularza csrf_token)
    z tokenem zapisanym w ciasteczku sesyjnym taxpilot_csrf_token za pomocą secrets.compare_digest.
    """
    import secrets

    from src.web.config import COOKIE_CSRF_TOKEN

    cookie_token = request.cookies.get(COOKIE_CSRF_TOKEN)
    if not cookie_token or not submitted_token:
        return False
    return secrets.compare_digest(submitted_token.strip(), cookie_token.strip())
