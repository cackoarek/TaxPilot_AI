"""
src/web/routers/settings.py
Kontroler Ustawień Firmy: konfiguracja profilu podatnika, środowiska i tokenu KSeF 2.0
oraz wyboru silnika AI (Multi-Provider LLM: Gemini, OpenAI, Claude, Zero-LLM).
"""
import os
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.config import TEMPLATES_DIR, get_llm_status
from src.web.dependencies import get_global_context

router = APIRouter(prefix="/ustawienia", tags=["Ustawienia Firmy"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def settings_view(request: Request):
    """Główny widok Ustawień Firmy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    # Pobierz aktualne ustawienia LLM z profil.json jeśli istnieją
    llm_saved_config = {}
    if profile:
        profile_file = profile.katalog_firmy / "profil.json"
        if profile_file.exists():
            try:
                with open(profile_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    llm_saved_config = data.get("llm", {})
            except Exception:
                pass

    ctx["llm_saved"] = llm_saved_config
    ctx["active_tab"] = "settings"

    return templates.TemplateResponse(request=request, name="pages/settings.html", context=ctx)


@router.post("/ksef", response_class=HTMLResponse)
async def update_ksef_settings(
    request: Request,
    token: str = Form(...),
    srodowisko: str = Form("PROD"),
):
    """Zapisuje token i środowisko KSeF w profil.json firmy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    token_clean = token.strip()
    env_clean = srodowisko.strip().upper()

    profile.set_ksef_token(token=token_clean, srodowisko=env_clean)

    return HTMLResponse(
        content="""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>✅</span>
                <span>Konfiguracja KSeF została pomyślnie zaktualizowana</span>
            </div>
            <p>Zapisano token i środowisko w <code>profil.json</code>. Możesz teraz synchronizować faktury z bramki Ministerstwa Finansów.</p>
        </div>
        """
    )


@router.post("/llm", response_class=HTMLResponse)
async def update_llm_settings(
    request: Request,
    provider: str = Form(...),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
):
    """Zapisuje konfigurację silnika AI (Multi-Provider) w profil.json i środowisku."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    provider_clean = provider.strip().lower()
    model_clean = (model or "").strip()
    key_clean = (api_key or "").strip()

    # Zaktualizuj zmienną środowiskową na czas sesji
    if provider_clean == "gemini" and key_clean:
        os.environ["GEMINI_API_KEY"] = key_clean
    elif provider_clean in ("claude", "anthropic") and key_clean:
        os.environ["ANTHROPIC_API_KEY"] = key_clean
    elif provider_clean == "openai" and key_clean:
        os.environ["OPENAI_API_KEY"] = key_clean
    elif provider_clean in ("null", "deterministic"):
        os.environ["TAXPILOT_LLM_PROVIDER"] = "null"

    if provider_clean != "auto":
        os.environ["TAXPILOT_LLM_PROVIDER"] = provider_clean

    # Zapisz w profil.json
    profile_file = profile.katalog_firmy / "profil.json"
    if profile_file.exists():
        try:
            with open(profile_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["llm"] = {
                "provider": provider_clean,
                "model": model_clean or "default",
            }
            with open(profile_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    status = get_llm_status()

    return HTMLResponse(
        content=f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>🤖</span>
                <span>Konfiguracja silnika AI została zapisana</span>
            </div>
            <p>Aktywny silnik: <strong>{status['label']}</strong>. Zmiana jest widoczna natychmiast w asystencie Copilot.</p>
        </div>
        """
    )
