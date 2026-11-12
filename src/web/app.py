"""
src/web/app.py
Główna aplikacja FastAPI dla TaxPilot AI (Wariant B: Server-Driven UI).
"""
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.web.config import STATIC_DIR, DEFAULT_HOST, DEFAULT_PORT, DEBUG
from src.web.routers import dashboard, companies, aml, settlement

app = FastAPI(
    title="TaxPilot AI",
    description="Autonomiczny Asystent Księgowo-Podatkowy JDG",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Montowanie plików statycznych (CSS, JS, obrazy)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Dołączanie routerów
app.include_router(dashboard.router)
app.include_router(companies.router)
app.include_router(aml.router)
app.include_router(settlement.router)


@app.get("/health")
async def health_check():
    """Prosty probe stanu serwera."""
    return {"status": "ok", "app": "TaxPilot AI", "mode": "web"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.web.app:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=DEBUG)
