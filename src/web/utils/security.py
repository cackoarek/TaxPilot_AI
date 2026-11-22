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


def is_trusted_origin(request: Request) -> bool:
    """
    Weryfikuje nagłówek Origin / Referer dla żądań mutujących stan (POST, PUT, DELETE, PATCH).
    W architekturze Local-First blokuje ataki CSRF ze złośliwych stron otwartych w innych kartach (SEC-11).
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")

    # Dozwolone zaufane hosty lokalne
    trusted_hosts = {"127.0.0.1", "localhost", "testserver"}
    if host:
        host_clean = host.split(":")[0].lower()
        if host_clean:
            trusted_hosts.add(host_clean)

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
        except Exception:
            return False

    return True
