"""
src/web/app.py
Główna aplikacja FastAPI dla TaxPilot AI (Wariant B: Server-Driven UI).
"""
import sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from src.logging_config import setup_logging, get_logger
from src.web.config import STATIC_DIR, DEFAULT_HOST, DEFAULT_PORT, DEBUG
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
