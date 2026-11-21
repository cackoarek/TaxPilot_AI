# ==============================================================================
# TaxPilot AI - Production Dockerfile (Local-First / Private Network Container)
# ==============================================================================
# Lekki, bezpieczny obraz kontenera zoptymalizowany pod uruchomienie lokalne
# oraz w zabezpieczonych sieciach prywatnych (Docker Desktop, VPN, Tailscale).
# Nie wymaga instalacji żadnych zewnętrznych narzędzi OS ani CLI na hoście.
# ==============================================================================

FROM python:3.10-slim

# Podstawowe zmienne środowiskowe Pythona
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TAXPILOT_HOST=0.0.0.0 \
    TAXPILOT_PORT=8000

# Instalacja certyfikatów CA dla bezpiecznych połączeń SSL (KSeF MF, API MF, LLM)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Utworzenie nieuprzywilejowanego użytkownika systemowego
RUN useradd -m -u 1000 -s /bin/bash taxpilot

WORKDIR /app

# Instalacja zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Skopiowanie kodu aplikacji
COPY src/ ./src/
COPY analysis/ ./analysis/

# Utworzenie domyślnego katalogu firm i ustawienie uprawnień
RUN mkdir -p /app/firmy && chown -R taxpilot:taxpilot /app

USER taxpilot

# Montowanie trwałego wolumenu z danymi podatników i fakturami
VOLUME ["/app/firmy"]

EXPOSE 8000

# Sprawdzanie stanu kontenera (Healthcheck)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Uruchomienie serwera ASGI (FastAPI + Uvicorn)
CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
