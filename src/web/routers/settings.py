"""
src/web/routers/settings.py
Kontroler Ustawień Firmy: konfiguracja profilu podatnika, środowiska i tokenu KSeF 2.0
oraz wyboru silnika AI (Multi-Provider LLM: Gemini, OpenAI, Claude, Zero-LLM).
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.core.company import TypZUS
from src.core.io import atomic_write_text
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_1_ingestion.xades_signer import parse_certificate_info, validate_key_pair
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

    # Informacje o certyfikatach KSeF firmy
    auth_cert_info = None
    auth_key_exists = False
    offline_cert_info = None
    offline_key_exists = False

    if profile:
        auth_cert_p = profile.get_auth_cert_path()
        if auth_cert_p:
            try:
                auth_cert_info = parse_certificate_info(auth_cert_p.read_bytes())
            except Exception as e:
                auth_cert_info = {"error": str(e), "is_valid": False}
        auth_key_exists = bool(profile.get_auth_key_path())

        offline_cert_p = profile.get_offline_cert_path()
        if offline_cert_p:
            try:
                offline_cert_info = parse_certificate_info(offline_cert_p.read_bytes())
            except Exception as e:
                offline_cert_info = {"error": str(e), "is_valid": False}
        offline_key_exists = bool(profile.get_offline_key_path())

    ctx["auth_cert_info"] = auth_cert_info
    ctx["auth_key_exists"] = auth_key_exists
    ctx["offline_cert_info"] = offline_cert_info
    ctx["offline_key_exists"] = offline_key_exists
    ctx["llm"] = llm_status
    ctx["llm_status"] = llm_status
    ctx["llm_saved"] = llm_saved_config
    ctx["active_tab"] = "settings"

    return templates.TemplateResponse(request=request, name="pages/settings.html", context=ctx)


@router.post("/ksef", response_class=HTMLResponse)
async def update_ksef_settings(
    request: Request,
    token: Optional[str] = Form(None),
    srodowisko: str = Form("PROD"),
    auth_type: str = Form("token"),
):
    """Zapisuje metodę uwierzytelniania, token i środowisko KSeF w profil.json firmy."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    token_clean = (token or "").strip()
    env_clean = srodowisko.strip().upper()
    auth_type_clean = auth_type.strip().lower()

    if auth_type_clean == "token" and not token_clean and not profile.ksef.token:
        return HTMLResponse(
            content="""
            <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>⚠️</span>
                    <span>Wprowadź token autoryzacyjny KSeF</span>
                </div>
                <p>Wybrano uwierzytelnianie tokenem, ale pole tokena pozostało puste.</p>
            </div>
            """
        )

    if auth_type_clean == "certyfikat" and not profile.has_ksef_certificate():
        return HTMLResponse(
            content="""
            <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>⚠️</span>
                    <span>Brak wgranego certyfikatu uwierzytelnienia</span>
                </div>
                <p>Aby przełączyć tryb na certyfikat, najpierw wgraj pliki <code>auth.crt</code> oraz <code>auth.key</code> w sekcji poniżej.</p>
            </div>
            """
        )

    profile.set_ksef_token(
        token=token_clean if token_clean else (profile.ksef.token or ""),
        srodowisko=env_clean,
        auth_type=auth_type_clean,
    )

    mode_label = (
        "Certyfikat KSeF (.crt + .key / XAdES-BES)" if auth_type_clean == "certyfikat" else "Token autoryzacyjny KSeF"
    )

    return HTMLResponse(
        content=f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>✅</span>
                <span>Konfiguracja KSeF została pomyślnie zaktualizowana</span>
            </div>
            <p>Zapisano w <code>profil.json</code>: Aktywna metoda: <strong>{mode_label}</strong> • Środowisko: <strong>{env_clean}</strong>.</p>
        </div>
        """
    )


@router.post("/ksef/certyfikaty", response_class=HTMLResponse)
async def upload_ksef_certificates(
    request: Request,
    auth_crt: Optional[UploadFile] = File(None),
    auth_key: Optional[UploadFile] = File(None),
    auth_password: Optional[str] = Form(None),
    offline_crt: Optional[UploadFile] = File(None),
    offline_key: Optional[UploadFile] = File(None),
    offline_password: Optional[str] = Form(None),
    switch_to_cert: Optional[str] = Form("true"),
    srodowisko: Optional[str] = Form(None),
):
    """
    Wgrywa i waliduje certyfikaty oraz klucze prywatne dla uwierzytelnienia oraz trybu offline.
    Zapisuje je bezpiecznie w katalogu firmy: firmy/{NIP}/certyfikaty/ (uprawnienia 0600).
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    auth_cert_bytes = await auth_crt.read() if auth_crt and auth_crt.filename else None
    auth_key_bytes = await auth_key.read() if auth_key and auth_key.filename else None
    offline_cert_bytes = await offline_crt.read() if offline_crt and offline_crt.filename else None
    offline_key_bytes = await offline_key.read() if offline_key and offline_key.filename else None

    if not (
        auth_cert_bytes
        or auth_key_bytes
        or offline_cert_bytes
        or offline_key_bytes
        or auth_password
        or offline_password
    ):
        return HTMLResponse(
            content="""
            <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>⚠️</span>
                    <span>Wybierz pliki certyfikatów lub kluczy do wgrania</span>
                </div>
                <p>Nie wybrano żadnego pliku (.crt lub .key).</p>
            </div>
            """
        )

    # Walidacja pary Uwierzytelnienia
    cert_to_check = auth_cert_bytes
    if not cert_to_check and profile.get_auth_cert_path():
        cert_to_check = profile.get_auth_cert_path().read_bytes()

    key_to_check = auth_key_bytes
    if not key_to_check and profile.get_auth_key_path():
        key_to_check = profile.get_auth_key_path().read_bytes()

    if cert_to_check and key_to_check:
        pwd_bytes = (
            auth_password.strip().encode("utf-8")
            if auth_password and auth_password.strip()
            else (profile.ksef.key_password.encode("utf-8") if profile.ksef.key_password else None)
        )
        valid, msg = validate_key_pair(cert_to_check, key_to_check, pwd_bytes)
        if not valid:
            return HTMLResponse(
                content=f"""
                <div class="p-4 bg-rose-50 text-rose-900 border border-rose-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                    <div class="flex items-center space-x-2 font-bold">
                        <span>❌</span>
                        <span>Błąd weryfikacji certyfikatu uwierzytelnienia</span>
                    </div>
                    <p class="font-mono text-[11px]">{msg}</p>
                    <p class="text-[11px] text-rose-700">Upewnij się, że plik .key odpowiada certyfikatowi .crt oraz że podano poprawne hasło (jeśli klucz jest chroniony hasłem).</p>
                </div>
                """
            )

    # Walidacja pary Offline
    off_cert_to_check = offline_cert_bytes
    if not off_cert_to_check and profile.get_offline_cert_path():
        off_cert_to_check = profile.get_offline_cert_path().read_bytes()

    off_key_to_check = offline_key_bytes
    if not off_key_to_check and profile.get_offline_key_path():
        off_key_to_check = profile.get_offline_key_path().read_bytes()

    if off_cert_to_check and off_key_to_check:
        off_pwd_bytes = (
            offline_password.strip().encode("utf-8")
            if offline_password and offline_password.strip()
            else (profile.ksef.offline_key_password.encode("utf-8") if profile.ksef.offline_key_password else None)
        )
        valid_off, msg_off = validate_key_pair(off_cert_to_check, off_key_to_check, off_pwd_bytes)
        if not valid_off:
            return HTMLResponse(
                content=f"""
                <div class="p-4 bg-rose-50 text-rose-900 border border-rose-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                    <div class="flex items-center space-x-2 font-bold">
                        <span>❌</span>
                        <span>Błąd weryfikacji certyfikatu trybu offline</span>
                    </div>
                    <p class="font-mono text-[11px]">{msg_off}</p>
                    <p class="text-[11px] text-rose-700">Upewnij się, że plik offline .key odpowiada certyfikatowi offline .crt.</p>
                </div>
                """
            )

    auth_type = "certyfikat" if (switch_to_cert and switch_to_cert.lower() in ("true", "1", "yes", "on")) else None

    profile.set_ksef_certificates(
        auth_cert_bytes=auth_cert_bytes,
        auth_key_bytes=auth_key_bytes,
        auth_password=auth_password,
        offline_cert_bytes=offline_cert_bytes,
        offline_key_bytes=offline_key_bytes,
        offline_password=offline_password,
        auth_type=auth_type,
        srodowisko=srodowisko,
    )

    uploaded_items = []
    if auth_cert_bytes:
        uploaded_items.append("Certyfikat uwierzytelnienia (auth.crt)")
    if auth_key_bytes:
        uploaded_items.append("Klucz prywatny uwierzytelnienia (auth.key)")
    if offline_cert_bytes:
        uploaded_items.append("Certyfikat trybu offline (offline.crt)")
    if offline_key_bytes:
        uploaded_items.append("Klucz trybu offline (offline.key)")

    summary_items = ", ".join(uploaded_items) if uploaded_items else "Zaktualizowano konfigurację haseł"

    return HTMLResponse(
        content=f"""
        <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
            <div class="flex items-center space-x-2 font-bold">
                <span>✅</span>
                <span>Certyfikaty KSeF zostały pomyślnie wgrane i zweryfikowane</span>
            </div>
            <p>Zapisano: <strong>{summary_items}</strong> w <code>firmy/{profile.katalog_nazwa}/certyfikaty/</code> (uprawnienia 0600).</p>
            <p class="text-[11px] text-emerald-700 font-medium mt-1">Ustawiono metodę autoryzacji na <strong>Certyfikat KSeF (XAdES-BES)</strong>. Odśwież stronę lub przetestuj połączenie przyciskiem poniżej.</p>
        </div>
        """
    )


@router.post("/ksef/test", response_class=HTMLResponse)
async def test_ksef_connection(request: Request):
    """Testuje połączenie i sesję z KSeF 2.0 (tokenem lub certyfikatem)."""
    ctx = get_global_context(request)
    profile = ctx["profile"]

    if not profile:
        raise HTTPException(status_code=400, detail="Brak profilu firmy")

    client = KSeFClient(profile)

    if not client.is_auth_configured():
        auth_type = (profile.ksef.auth_type or "token").lower()
        if auth_type == "certyfikat":
            detail = "Brak wgranego kompletu certyfikat + klucz (auth.crt i auth.key)."
        else:
            detail = "Brak skonfigurowanego tokenu KSeF."
        return HTMLResponse(
            content=f"""
            <div class="p-4 bg-amber-50 text-amber-900 border border-amber-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>⚠️</span>
                    <span>Brak konfiguracji uwierzytelnienia</span>
                </div>
                <p>{detail}</p>
            </div>
            """
        )

    try:
        res = client.test_connection()
        auth_name = "Certyfikat (XAdES-BES)" if res.get("auth_type") == "certyfikat" else "Token autoryzacyjny"
        valid_until = res.get("valid_until", "Sesja aktywna")
        return HTMLResponse(
            content=f"""
            <div class="p-4 bg-emerald-50 text-emerald-900 border border-emerald-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>🏛️</span>
                    <span>Połączenie z KSeF 2.0 nawiązane pomyślnie!</span>
                </div>
                <p>Metoda: <strong>{auth_name}</strong> • Środowisko: <strong>{res.get("srodowisko")}</strong></p>
                <p class="text-[11px] text-emerald-700 font-mono">JWT access_token odebrany. Ważny do: {valid_until}</p>
            </div>
            """
        )
    except Exception as e:
        logger.error("Błąd testu połączenia z KSeF dla %s: %s", profile.nip, e)
        return HTMLResponse(
            content=f"""
            <div class="p-4 bg-rose-50 text-rose-900 border border-rose-300 rounded-xl text-xs space-y-1 shadow-xs fade-in">
                <div class="flex items-center space-x-2 font-bold">
                    <span>❌</span>
                    <span>Błąd testu połączenia z KSeF</span>
                </div>
                <p class="font-mono text-[11px]">{str(e)}</p>
                <p class="text-[11px] text-rose-700">Sprawdź, czy środowisko KSeF ({profile.ksef.srodowisko}) jest dostępne i dane autoryzacyjne są poprawne.</p>
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
    """
    Zapisuje lub aktualizuje klucz w lokalnym pliku .env (ignorowanym przez git).
    Zabezpiecza przed CRLF injection (SEC-18) oraz zapisuje atomowo z uprawnieniami 0600 i blokadą.
    """
    # Pobierz wyłącznie pierwszą linię (ochrona przed wstrzyknięciem wieloliniowym / CRLF)
    first_name_line = key_name.strip().splitlines()[0] if key_name.strip() else ""
    first_val_line = key_val.strip().splitlines()[0] if key_val.strip() else ""

    clean_name = re.sub(r"[^A-Za-z0-9_]", "", first_name_line)
    clean_val = re.sub(r"[\r\n]", "", first_val_line)
    if not clean_name:
        return

    env_file = Path(".env")
    lines = []
    found = False
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{clean_name}="):
                lines[i] = f"{clean_name}={clean_val}"
                found = True
                break
    if not found:
        lines.append(f"{clean_name}={clean_val}")

    atomic_write_text(
        env_file,
        "\n".join(lines) + "\n",
        encoding="utf-8",
        mode=0o600,
        lock=True,
    )


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
