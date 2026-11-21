"""
src/web/routers/settings.py
Kontroler Ustawień Firmy: konfiguracja profilu podatnika, środowiska i tokenu KSeF 2.0
oraz wyboru silnika AI (Multi-Provider LLM: Gemini, OpenAI, Claude, Zero-LLM).
"""

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.core.company import TypZUS
from src.logging_config import get_logger
from src.web.config import TEMPLATES_DIR, get_llm_status
from src.web.dependencies import get_global_context

logger = get_logger("taxpilot.settings")
router = APIRouter(prefix="/ustawienia", tags=["Ustawienia Firmy"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def settings_view(request: Request):
    """Główny widok Ustawień Firmy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    # Pobierz aktualne ustawienia LLM z obiektu profilu lub pliku profil.json
    llm_saved_config = {}
    if profile:
        if getattr(profile, "llm", None):
            llm_saved_config = dict(profile.llm)
        else:
            profile_file = profile.katalog_firmy / "profil.json"
            if profile_file.exists():
                try:
                    with open(profile_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        llm_saved_config = data.get("llm", {})
                except Exception:
                    pass

    # Uzupełnij ze środowiska / .env jeśli nie było w profil.json
    if not llm_saved_config.get("model") and os.getenv("TAXPILOT_LLM_MODEL"):
        llm_saved_config["model"] = os.getenv("TAXPILOT_LLM_MODEL")
    if not llm_saved_config.get("provider") and os.getenv("TAXPILOT_LLM_PROVIDER"):
        llm_saved_config["provider"] = os.getenv("TAXPILOT_LLM_PROVIDER")

    # Pobierz pełny status LLM z uwzględnieniem profilu
    llm_status = get_llm_status(profile)
    if not llm_saved_config.get("provider"):
        llm_saved_config["provider"] = llm_status.get("provider", "auto")
    if not llm_saved_config.get("model"):
        llm_saved_config["model"] = llm_status.get("model", "")

    ctx["llm"] = llm_status
    ctx["llm_status"] = llm_status
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


@router.post("/podatki", response_class=HTMLResponse)
async def update_tax_settings(
    request: Request,
    stawka_ryczaltu: float = Form(...),
    typ_zus: str = Form(...),
    chorobowe_dobrowolne: Optional[str] = Form(None),
    platnik_vat: Optional[str] = Form(None),
    zasada_odliczen: Optional[str] = Form(None),
    metoda_zdrowotna: Optional[str] = Form(None),
    prog_zdrowotnej_uproszczony: Optional[str] = Form(None),
):
    """Zapisuje zmienne parametry podatkowe i składkowe JDG w profil.json firmy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    # Walidacja typu ZUS
    try:
        typ_zus_enum = TypZUS(typ_zus.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Nieprawidłowy typ ZUS: {typ_zus}")

    is_chorobowe = bool(chorobowe_dobrowolne and chorobowe_dobrowolne.lower() in ("true", "1", "on", "yes"))
    is_vat = bool(platnik_vat and platnik_vat.lower() in ("true", "1", "on", "yes"))

    profile.update_tax_and_zus_settings(
        domyslna_stawka_ryczaltu=stawka_ryczaltu,
        typ_zus=typ_zus_enum,
        chorobowe_dobrowolne=is_chorobowe,
        platnik_vat=is_vat,
        zasada_odliczen=zasada_odliczen,
        metoda_zdrowotna=metoda_zdrowotna,
        prog_zdrowotnej_uproszczony=prog_zdrowotnej_uproszczony,
    )

    logger.info(
        "Zaktualizowano parametry firmy %s: stawka=%.1f%%, ZUS=%s, chorobowe=%s, VAT=%s, zasada=%s, zdrowotna=%s",
        profile.nip,
        stawka_ryczaltu * 100,
        typ_zus_enum.value,
        is_chorobowe,
        is_vat,
        zasada_odliczen or profile.zus.zasada_odliczen,
        metoda_zdrowotna or profile.zus.metoda_zdrowotna,
    )

    stawka_procent = (
        int(stawka_ryczaltu * 100) if (stawka_ryczaltu * 100).is_integer() else f"{stawka_ryczaltu * 100:.1f}"
    )

    return HTMLResponse(
        content=f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>✅</span>
                <span>Parametry podatkowo-składkowe zostały pomyślnie zaktualizowane</span>
            </div>
            <p>Zapisano w <code>profil.json</code>: Domyślna stawka ryczałtu: <strong>{stawka_procent}%</strong> • Pakiet ZUS: <strong>{typ_zus_enum.value}</strong> • Dobrowolne chorobowe: <strong>{"TAK" if is_chorobowe else "NIE"}</strong> • Płatnik VAT: <strong>{"TAK (Czynny)" if is_vat else "NIE (Zwolniony)"}</strong>.</p>
            <p class="text-[11px] text-emerald-700 font-medium mt-1">Zmiany będą automatycznie uwzględniane w kolejnych kalkulacjach księgowych i rozliczeniach ZUS/PIT-28/VAT-7.</p>
        </div>
        """
    )


def save_key_to_env(key_name: str, key_val: str):
    """Zapisuje lub aktualizuje klucz w lokalnym pliku .env (ignorowanym przez git)."""
    env_file = Path(".env")
    lines = []
    found = False
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key_name}="):
                lines[i] = f"{key_name}={key_val}"
                found = True
                break
    if not found:
        lines.append(f"{key_name}={key_val}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


@router.post("/llm", response_class=HTMLResponse)
async def update_llm_settings(
    request: Request,
    provider: str = Form(...),
    model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
):
    """Zapisuje konfigurację silnika AI (Multi-Provider) w profil.json, pliku .env i środowisku."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    provider_clean = provider.strip().lower()
    model_clean = (model or "").strip()
    key_clean = (api_key or "").strip()

    # Zaktualizuj zmienną środowiskową na czas sesji oraz utrwal w .env
    if provider_clean in ("antigravity", "agy", "local", "cli"):
        provider_clean = "antigravity"
        os.environ["TAXPILOT_LLM_PROVIDER"] = "antigravity"
        save_key_to_env("TAXPILOT_LLM_PROVIDER", "antigravity")
    elif provider_clean == "gemini" and key_clean:
        os.environ["GEMINI_API_KEY"] = key_clean
        save_key_to_env("GEMINI_API_KEY", key_clean)
    elif provider_clean in ("claude", "anthropic") and key_clean:
        os.environ["ANTHROPIC_API_KEY"] = key_clean
        save_key_to_env("ANTHROPIC_API_KEY", key_clean)
    elif provider_clean == "openai" and key_clean:
        os.environ["OPENAI_API_KEY"] = key_clean
        save_key_to_env("OPENAI_API_KEY", key_clean)
    elif provider_clean in ("null", "deterministic"):
        os.environ["TAXPILOT_LLM_PROVIDER"] = "null"
        save_key_to_env("TAXPILOT_LLM_PROVIDER", "null")

    if provider_clean not in ("auto", "antigravity", "null", "deterministic"):
        os.environ["TAXPILOT_LLM_PROVIDER"] = provider_clean
        save_key_to_env("TAXPILOT_LLM_PROVIDER", provider_clean)

    # Zapisz model w środowisku i pliku .env
    if model_clean:
        os.environ["TAXPILOT_LLM_MODEL"] = model_clean
        save_key_to_env("TAXPILOT_LLM_MODEL", model_clean)
    else:
        os.environ.pop("TAXPILOT_LLM_MODEL", None)

    # Zaktualizuj profil firmy w pamięci i na dysku (profil.json)
    if hasattr(profile, "set_llm_config"):
        profile.set_llm_config(provider=provider_clean, model=model_clean)
    else:
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
            except Exception as e:
                logger.error("Błąd zapisu llm w profil.json: %s", e)

    logger.info(
        "Zapisano nową konfigurację silnika AI: provider=%s, model=%s, klucz_podany=%s",
        provider_clean,
        model_clean or "(domyślny)",
        bool(key_clean),
    )

    status = get_llm_status(profile)

    return HTMLResponse(
        content=f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>🤖</span>
                <span>Konfiguracja silnika AI została zapisana</span>
            </div>
            <p>Aktywny silnik: <strong>{status["label"]}</strong>. Zmiana jest widoczna natychmiast w asystencie Copilot.</p>
        </div>
        """
    )
