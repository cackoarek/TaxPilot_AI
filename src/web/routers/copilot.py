"""
src/web/routers/copilot.py
Kontroler asystenta AI Copilot (SSE Streaming & HTMX chat).
"""

import html
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.core.company import CompanyProfile
from src.logging_config import get_logger
from src.web.config import TEMPLATES_DIR, get_llm_status
from src.web.dependencies import get_global_context
from src.web.services.chat_session_service import (
    ChatMessageRecord,
    ChatSession,
    ChatSessionManager,
)
from src.web.services.copilot_service import CopilotService
from src.web.services.llm.base import ChatMessage
from src.web.utils.markdown import is_safe_url, render_markdown

__all__ = ["router", "is_safe_url", "markdown_to_html", "log_ai_interaction"]

logger = get_logger("taxpilot.copilot")
router = APIRouter(prefix="/api/copilot", tags=["AI Copilot"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

AI_ASSISTANT_LOG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "ai_assistant.log"


def log_ai_interaction(
    user_message: str, assistant_response: str, nip: Optional[str] = None, okres: Optional[str] = None
) -> None:
    """Zapisuje każde zapytanie użytkownika i odpowiedź asystenta do pliku logów ai_assistant.log."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"[{timestamp}] [OKRES: {okres or 'N/A'}] [NIP: {nip or 'N/A'}]\n"
            f"USER:\n{user_message.strip()}\n"
            f"ASSISTANT:\n{assistant_response.strip()}\n"
            f"{'-' * 80}\n"
        )
        with open(AI_ASSISTANT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.warning("Nie udało się zapisać do ai_assistant.log: %s", e)


def markdown_to_html(text: str) -> str:
    """Konwertuje markdown na bezpieczny i estetyczny kod HTML dla dymków czatu na stronie WWW."""
    return str(render_markdown(text, header_shift=1))


CopilotMessageRecord = ChatMessageRecord


class CopilotSessionHistory:
    _history: dict = {}
    _running_tasks: dict = {}

    @classmethod
    def get_messages(cls, session_id: str) -> list:
        return cls._history.get(session_id, [])

    @classmethod
    def get_message_by_id(cls, session_id: str, record_id: str) -> Optional[ChatMessageRecord]:
        for r in cls._history.get(session_id, []):
            if r.id == record_id:
                return r
        for msgs in cls._history.values():
            for r in msgs:
                if r.id == record_id:
                    return r
        return None

    @classmethod
    def add_message(cls, session_id: str, user_msg: str) -> ChatMessageRecord:
        record = ChatMessageRecord(
            id=str(uuid.uuid4())[:8],
            user_message=user_msg,
            assistant_message="",
            assistant_raw="",
            status="pending",
            created_at=datetime.now().strftime("%H:%M:%S"),
            created_timestamp=time.time(),
        )
        cls._history.setdefault(session_id, []).append(record)
        return record

    @classmethod
    def update_message(cls, session_id: str, record_id: str, assistant_msg: str, status: str = "done"):
        for r in cls._history.get(session_id, []):
            if r.id == record_id:
                r.assistant_message = assistant_msg
                r.status = status
                break

    @classmethod
    def clear(cls, session_id: str):
        if session_id in cls._running_tasks:
            t = cls._running_tasks[session_id]
            if not t.done():
                t.cancel()
            del cls._running_tasks[session_id]
        cls._history[session_id] = []
        if session_id.startswith("company_"):
            nip = session_id.replace("company_", "")
            profile = CompanyProfile.load_by_nip(nip)
            if profile:
                active = ChatSessionManager.get_active_session(profile, create_if_none=False)
                if active:
                    active.messages = []
                    ChatSessionManager.save_session(profile, active)


def render_user_bubble(user_message: str) -> str:
    escaped = html.escape(user_message, quote=True)
    return f"""
    <div class="flex space-x-3 justify-end my-2">
      <div class="bg-blue-600 text-white p-3 rounded-2xl rounded-tr-none shadow-sm text-xs max-w-[85%] break-words">
        {escaped}
      </div>
      <div class="flex-shrink-0 w-8 h-8 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center text-xs font-bold">
        Ty
      </div>
    </div>
    """


def render_assistant_bubble(assistant_html: str, record_id: str = "") -> str:
    id_attr = f'id="copilot-msg-{record_id}" ' if record_id else ""
    return f"""
    <div {id_attr}class="flex space-x-3 my-2">
      <div class="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white text-xs font-bold shadow-xs">
        🤖
      </div>
      <div class="bg-white p-3 rounded-2xl rounded-tl-none border border-slate-200 shadow-sm text-xs text-slate-800 space-y-1.5 max-w-[95%] break-words leading-relaxed flex-1">
        <div class="prose prose-xs max-w-none">
          {assistant_html}
        </div>
      </div>
    </div>
    """


def render_pending_bubble(record_id: str, elapsed_sec: int = 0) -> str:
    time_badge = (
        f'<span class="text-blue-500 font-mono text-[11px] ml-1">({elapsed_sec}s)</span>' if elapsed_sec > 0 else ""
    )
    tip_str = (
        '<span class="text-[10px] text-slate-400 block font-normal mt-0.5">Asystent analizuje rejestry księgowe i wykonuje obliczenia (Zero-Hallucination)...</span>'
        if elapsed_sec >= 6
        else ""
    )
    return f"""
    <div id="copilot-active-loader"
         data-msg-id="{record_id}"
         hx-get="/api/copilot/message-status?id={record_id}"
         hx-trigger="every 1s"
         hx-target="this"
         hx-swap="outerHTML"
         class="flex space-x-3 my-2">
      <div class="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white text-xs font-bold shadow-xs animate-spin">
        🤖
      </div>
      <div class="bg-white p-3 rounded-2xl rounded-tl-none border border-blue-200 shadow-xs text-xs text-slate-700 space-y-1 max-w-[85%]">
        <div class="flex items-center space-x-2 text-blue-600 font-semibold">
          <span class="animate-pulse">● ● ●</span>
          <span>Asystent AI analizuje dane i przygotowuje odpowiedź...{time_badge}</span>
        </div>
        {tip_str}
      </div>
    </div>
    """


def render_session_title_bar(session: Optional[ChatSession], oob: bool = False) -> str:
    oob_attr = 'hx-swap-oob="outerHTML:#copilot-active-session-title-container"' if oob else ""
    if not session:
        title = "Nowa rozmowa"
        sess_id = ""
    else:
        title = session.title or "Nowa rozmowa"
        sess_id = session.id
    escaped_title = html.escape(title, quote=True)
    return f"""
    <div class="flex items-center space-x-2 flex-1 min-w-0 mr-2" id="copilot-active-session-title-container" {oob_attr}>
      <span class="text-blue-400 flex-shrink-0">💬</span>
      <div x-show="!editingTitle" class="flex items-center space-x-1.5 truncate">
        <span id="copilot-session-title" class="font-semibold text-white truncate cursor-pointer hover:text-blue-300 transition-colors"
              @click="editingTitle = true"
              title="Kliknij, aby zmienić nazwę tej rozmowy">
          {escaped_title}
        </span>
        <button type="button" @click="editingTitle = true" class="text-slate-400 hover:text-white p-0.5 rounded cursor-pointer" title="Zmień nazwę rozmowy">
          ✏️
        </button>
      </div>
      <form x-show="editingTitle" x-cloak
            hx-post="/api/copilot/session-rename"
            hx-target="#copilot-active-session-title-container"
            hx-swap="outerHTML"
            @submit="editingTitle = false"
            class="flex items-center space-x-1.5 flex-1">
        <input type="hidden" name="session_id" value="{sess_id}">
        <input type="text" name="title" value="{escaped_title}" required maxlength="60"
               class="bg-slate-900 border border-blue-500 rounded px-2 py-0.5 text-xs text-white focus:outline-none flex-1">
        <button type="submit" class="px-2 py-0.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-[11px] font-medium cursor-pointer">
          Zapisz
        </button>
        <button type="button" @click="editingTitle = false" class="px-1.5 py-0.5 text-slate-400 hover:text-white text-xs cursor-pointer">
          ✕
        </button>
      </form>
    </div>
    """


def render_sessions_list(profile: Optional[CompanyProfile], active_id: str) -> str:
    sessions = ChatSessionManager.list_sessions(profile)
    if not sessions:
        return (
            '<div class="text-center py-6 text-slate-400 text-xs">'
            "Brak zapisanych rozmów dla tej firmy.<br>"
            '<span class="text-slate-500 text-[11px]">Zadaj pytanie w oknie czatu, a wątek zostanie automatycznie zarchiwizowany!</span>'
            "</div>"
        )

    items = []
    for s in sessions:
        is_active = s["id"] == active_id
        active_class = (
            "bg-blue-950/80 border-blue-500 text-white shadow-xs"
            if is_active
            else "bg-slate-800/60 hover:bg-slate-800 border-slate-700/60 text-slate-300 hover:text-white"
        )
        badge = (
            '<span class="px-1.5 py-0.5 rounded bg-blue-600 text-white text-[10px] font-semibold flex-shrink-0">✓ Aktywna</span>'
            if is_active
            else ""
        )
        escaped_title = html.escape(s["title"], quote=True)
        snippet = html.escape(s.get("snippet", ""), quote=True)
        snippet_html = f'<p class="text-[11px] text-slate-400 truncate mt-0.5">↳ {snippet}</p>' if snippet else ""

        items.append(f"""
        <div class="p-2.5 rounded-lg border {active_class} transition-all flex items-start justify-between group">
          <button type="button"
                  hx-post="/api/copilot/sessions/{s["id"]}/select"
                  hx-target="#copilot-chat-container"
                  hx-swap="innerHTML"
                  @click="historyOpen = false"
                  class="flex-1 text-left min-w-0 pr-2 cursor-pointer">
            <div class="flex items-center justify-between gap-1">
              <span class="font-semibold text-xs truncate">{escaped_title}</span>
              {badge}
            </div>
            {snippet_html}
            <div class="flex items-center space-x-2 text-[10px] text-slate-400 mt-1">
              <span>📅 {s["display_date"]}</span>
              <span>•</span>
              <span>Okres: {s["rok"]}-{s["miesiac"]}</span>
              <span>•</span>
              <span>💬 {s["messages_count"]} wiad.</span>
            </div>
          </button>
          <div class="flex items-center space-x-1 opacity-70 group-hover:opacity-100 flex-shrink-0 mt-0.5">
            <button type="button"
                    hx-delete="/api/copilot/sessions/{s["id"]}"
                    hx-target="#copilot-sessions-list"
                    hx-swap="innerHTML"
                    hx-confirm="Czy na pewno chcesz bezpowrotnie usunąć tę rozmowę z historii?"
                    title="Usuń tę rozmowę z historii"
                    class="p-1 text-slate-400 hover:text-rose-400 hover:bg-slate-700 rounded transition-colors cursor-pointer text-xs">
              🗑️
            </button>
          </div>
        </div>
        """)
    return "\n".join(items)


@router.get("/status")
async def copilot_status():
    """Zwraca aktualny stan dostępności i konfiguracji modeli LLM."""
    return get_llm_status()


@router.get("/active-title", response_class=HTMLResponse)
async def get_active_title(request: Request):
    """Zwraca pasek z tytułem bieżącej aktywnej rozmowy."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac)
    return HTMLResponse(render_session_title_bar(session))


@router.get("/sessions", response_class=HTMLResponse)
async def get_copilot_sessions(request: Request):
    """Zwraca listę zapisanych sesji czatu dla firmy."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    active_session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac)
    active_id = active_session.id if active_session else ""
    return HTMLResponse(render_sessions_list(profile, active_id))


@router.post("/sessions/new", response_class=HTMLResponse)
async def new_copilot_session(request: Request):
    """Tworzy nowy, czysty wątek rozmowy i ustawia go jako aktywny."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    nazwa_firmy = profile.nazwa if profile else "TaxPilot"

    session = ChatSessionManager.create_new_session(profile, rok=rok, miesiac=miesiac, title="Nowa rozmowa")
    nip = profile.nip if profile else "default"
    CopilotSessionHistory.clear(f"company_{nip}")

    title_oob = render_session_title_bar(session, oob=True)

    welcome_html = f"""
    {title_oob}
    <div class="flex space-x-3 my-2">
      <div class="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shadow-xs">
        TP
      </div>
      <div class="bg-white p-3 rounded-2xl rounded-tl-none border border-slate-200 shadow-sm text-xs text-slate-700 space-y-1.5 max-w-[85%]">
        <p class="font-semibold text-slate-900">Nowy wątek rozmowy</p>
        <p>Rozpoczęto nową sesję dla firmy <strong class="text-blue-700">{nazwa_firmy}</strong> na okres <strong>{rok}-{miesiac}</strong>.</p>
        <p class="text-slate-500 text-[11px]">Zadaj pytanie asystentowi w polu poniżej. Rozmowa zostanie automatycznie zarchiwizowana w historii.</p>
      </div>
    </div>
    """
    return HTMLResponse(welcome_html, headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})})


@router.post("/sessions/{session_id}/select", response_class=HTMLResponse)
async def select_copilot_session(request: Request, session_id: str):
    """Przełącza aktywną rozmowę na wybraną z historii i wczytuje jej dymki."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")

    session = ChatSessionManager.load_session(profile, session_id)
    if not session:
        return HTMLResponse('<div class="p-4 text-center text-rose-500 text-xs">Nie znaleziono wybranej rozmowy.</div>')

    ChatSessionManager.set_active_session_id(profile, session.id)
    nip = profile.nip if profile else "default"

    CopilotSessionHistory._history[f"company_{nip}"] = list(session.messages)

    bubbles = []
    if not session.messages:
        bubbles.append(f"""
        <div class="p-3 my-2 bg-blue-50/70 border border-blue-200 rounded-xl text-xs text-slate-700">
          <p class="font-semibold text-blue-900">Rozmowa: {session.title}</p>
          <p class="text-slate-500 text-[11px] mt-0.5">Ten wątek nie zawiera jeszcze wiadomości. Zadaj pytanie poniżej, aby rozpocząć!</p>
        </div>
        """)
    else:
        for r in session.messages:
            bubbles.append(render_user_bubble(r.user_message))
            if r.status in ("done", "error"):
                bubbles.append(render_assistant_bubble(r.assistant_message, record_id=r.id))
            elif r.status == "pending":
                bubbles.append(render_pending_bubble(r.id))

    title_oob = render_session_title_bar(session, oob=True)
    content = f"{title_oob}\n{''.join(bubbles)}"
    return HTMLResponse(content, headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})})


@router.post("/session-rename", response_class=HTMLResponse)
async def rename_active_session(request: Request, session_id: str = Form(...), title: str = Form(...)):
    """Zmienia tytuł sesji czatu."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")

    ChatSessionManager.rename_session(profile, session_id, title)
    session = ChatSessionManager.load_session(profile, session_id)
    return HTMLResponse(
        render_session_title_bar(session), headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})}
    )


@router.delete("/sessions/{session_id}", response_class=HTMLResponse)
async def delete_copilot_session(request: Request, session_id: str):
    """Usuwa rozmowę z historii firmy."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")

    ChatSessionManager.delete_session(profile, session_id)
    active_session = ChatSessionManager.get_active_session(profile, ctx.get("rok", "2026"), ctx.get("miesiac", "01"))
    active_id = active_session.id if active_session else ""

    list_html = render_sessions_list(profile, active_id)
    title_oob = render_session_title_bar(active_session, oob=True)

    return HTMLResponse(
        f"{title_oob}\n{list_html}",
        headers={"HX-Trigger": json.dumps({"copilot-refresh-title": True, "copilot-refresh": True})},
    )


@router.get("/message-status", response_class=HTMLResponse)
async def get_message_status(request: Request, id: str = Query(...)):
    """
    Sprawdza stan przetwarzania konkretnej wiadomości przez asystenta AI.
    Odpytuje wyłącznie pojedynczy dymek wskaźnika oczekiwania (hx-target="this"),
    dzięki czemu istniejące wiadomości w czacie nigdy nie migają ani nie znikają.
    """
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    nip = profile.nip if profile else "default"
    session_id = f"company_{nip}"

    chat_session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac)
    record = chat_session.get_message_by_id(id) if chat_session else None
    if not record:
        record = CopilotSessionHistory.get_message_by_id(session_id, id)
        if not record:
            return ""

    running_task = ChatSessionManager._running_tasks.get(chat_session.id if chat_session else session_id)
    if running_task is None:
        running_task = CopilotSessionHistory._running_tasks.get(session_id)
    task_alive = running_task is not None and not running_task.done()

    if record.status == "pending" and not task_alive:
        age = time.time() - getattr(record, "created_timestamp", time.time())
        if age > 5.0:
            record.status = "error"
            record.assistant_message = (
                "⚠️ **Zadanie asystenta zostało przerwane.**\n\n"
                "Proces w tle nie zwrócił odpowiedzi. Kliknij przycisk **➕ Nowa** w nagłówku czatu i ponów zapytanie."
            )
            if chat_session:
                ChatSessionManager.save_session(profile, chat_session)

    if record.status in ("done", "error"):
        return render_assistant_bubble(record.assistant_message, record_id=record.id)
    else:
        elapsed = int(time.time() - getattr(record, "created_timestamp", time.time()))
        return render_pending_bubble(record.id, elapsed_sec=elapsed)


@router.get("/history", response_class=HTMLResponse)
async def get_copilot_history(request: Request):
    """Zwraca pełną historię rozmowy dla bieżącej aktywnej sesji firmy."""
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    nip = profile.nip if profile else "default"
    session_id = f"company_{nip}"

    chat_session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac)
    records = (
        chat_session.messages
        if chat_session and chat_session.messages
        else CopilotSessionHistory.get_messages(session_id)
    )
    if not records:
        return ""

    now = time.time()
    running_task = ChatSessionManager._running_tasks.get(chat_session.id if chat_session else session_id)
    if running_task is None:
        running_task = CopilotSessionHistory._running_tasks.get(session_id)
    task_alive = running_task is not None and not running_task.done()

    html_parts = []
    for r in records:
        if r.status == "pending" and not task_alive:
            age = now - getattr(r, "created_timestamp", now)
            if age > 5.0:
                r.status = "error"
                r.assistant_message = (
                    "⚠️ **Zadanie asystenta zostało przerwane.**\n\n"
                    "Proces w tle nie zwrócił odpowiedzi. Kliknij przycisk **➕ Nowa** w nagłówku czatu i ponów zapytanie."
                )
                if chat_session:
                    ChatSessionManager.save_session(profile, chat_session)

        html_parts.append(render_user_bubble(r.user_message))
        if r.status in ("done", "error"):
            html_parts.append(render_assistant_bubble(r.assistant_message, record_id=r.id))
        elif r.status == "pending":
            html_parts.append(render_pending_bubble(r.id))

    return "".join(html_parts)


@router.post("/reset", response_class=HTMLResponse)
async def copilot_reset(request: Request):
    """
    Resetuje bieżącą sesję asystenta AI dla aktywnej firmy, przerywa ewentualne
    trwające procesy w tle i restartuje czat tworząc nową sesję.
    """
    ctx = get_global_context(request)
    profile = ctx.get("profile")
    rok = ctx.get("rok", "2026")
    miesiac = ctx.get("miesiac", "01")
    nip = profile.nip if profile else "default"
    session_id = f"company_{nip}"

    new_session = ChatSessionManager.create_new_session(profile, rok=rok, miesiac=miesiac, title="Nowa rozmowa")
    CopilotSessionHistory.clear(session_id)

    from src.web.services.llm.antigravity_provider import AntigravitySessionManager

    AntigravitySessionManager.reset_session(session_id)
    nazwa_firmy = profile.nazwa if profile else "TaxPilot"
    logger.info("Zresetowano sesję AI Copilot dla firmy: %s (session_id=%s)", nazwa_firmy, session_id)

    title_oob = render_session_title_bar(new_session, oob=True)

    return HTMLResponse(
        f"""
    {title_oob}
    <div class="flex space-x-3 my-2">
      <div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center text-white text-xs font-bold shadow-xs">
        TP
      </div>
      <div class="bg-emerald-50 p-3 rounded-2xl rounded-tl-none border border-emerald-200 shadow-xs text-xs text-slate-700 space-y-1 max-w-[85%]">
        <p class="font-semibold text-emerald-800 flex items-center gap-1">
          <span>🔄</span> Sesja AI została pomyślnie zresetowana!
        </p>
        <p class="text-slate-600">Rozpoczęto nową, czystą sesję dla firmy <strong>{nazwa_firmy}</strong> na okres <strong>{rok}-{miesiac}</strong>.</p>
        <p class="text-slate-500 text-[11px]">Wszelkie wiszące procesy zostały zatrzymane. Możesz zadać nowe pytanie.</p>
      </div>
    </div>
    """,
        headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})},
    )


@router.post("/chat", response_class=HTMLResponse)
async def copilot_chat(
    request: Request,
    message: str = Form(...),
    stream: bool = Query(False),
):
    """
    Endpoint obsługujący zapytania do asystenta AI Copilot.
    Wspiera asynchroniczne tło, SSE streaming, trwałość sesji na dysku
    oraz pełny kontekst wieloturowy (Multi-turn conversational memory).
    """
    import asyncio

    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]
    nip = profile.nip if profile else "default"
    session_id = f"company_{nip}"

    user_msg_clean = message.strip()
    if not user_msg_clean:
        raise HTTPException(status_code=400, detail="Wiadomość nie może być pusta.")

    # Trwała sesja na dysku
    chat_session = ChatSessionManager.get_active_session(profile, rok=rok, miesiac=miesiac)
    if not chat_session:
        raise HTTPException(status_code=400, detail="Brak aktywnej sesji czatu dla wybranego okresu.")
    record = chat_session.add_user_message(user_msg_clean)
    ChatSessionManager.save_session(profile, chat_session)

    # Replikacja w pamięci dla testów
    hist_record = CopilotSessionHistory.add_message(session_id, user_msg_clean)
    hist_record.id = record.id

    # Budowanie wieloturowego kontekstu rozmowy (Multi-turn conversational memory)
    llm_messages = []
    for m in chat_session.messages:
        if m.id == record.id:
            continue
        if m.status == "done" and (m.assistant_raw or m.assistant_message):
            llm_messages.append(ChatMessage(role="user", content=m.user_message))
            content = m.assistant_raw if m.assistant_raw else m.assistant_message
            llm_messages.append(ChatMessage(role="assistant", content=content))
    llm_messages.append(ChatMessage(role="user", content=user_msg_clean))

    logger.info(
        "Otrzymano zapytanie do Copilota: %s (tury=%d, stream=%s)", user_msg_clean[:60], len(llm_messages), stream
    )

    # Obsługa SSE Streaming
    accept_header = request.headers.get("accept", "")
    if stream or "text/event-stream" in accept_header:

        async def event_generator():
            accumulated_tokens = []
            try:
                async for token in CopilotService.stream_chat(
                    llm_messages, profile, rok, miesiac, session_id=chat_session.id
                ):
                    accumulated_tokens.append(token)
                    yield f"data: {json.dumps({'delta': token})}\n\n"
                full_stream_resp = "".join(accumulated_tokens)
                log_ai_interaction(
                    user_msg_clean, full_stream_resp, nip=profile.nip if profile else None, okres=f"{rok}-{miesiac}"
                )
                html_resp = markdown_to_html(full_stream_resp)
                chat_session.update_message(record.id, html_resp, assistant_raw=full_stream_resp, status="done")
                ChatSessionManager.save_session(profile, chat_session)
                CopilotSessionHistory.update_message(session_id, record.id, html_resp, status="done")
            except Exception as e:
                logger.exception("Błąd podczas strumieniowania Copilota: %s", e)
                err_text = f"\n\n⚠️ **Błąd komunikacji z modelem AI:**\n> {str(e)}\n\n*Wskazówka:* Sprawdź klucz API oraz nazwę modelu w zakładce **Ustawienia**."
                yield f"data: {json.dumps({'delta': err_text})}\n\n"
                log_ai_interaction(
                    user_msg_clean, f"BŁĄD: {e}", nip=profile.nip if profile else None, okres=f"{rok}-{miesiac}"
                )
                chat_session.update_message(record.id, err_text, assistant_raw=err_text, status="error")
                ChatSessionManager.save_session(profile, chat_session)
                CopilotSessionHistory.update_message(session_id, record.id, err_text, status="error")
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Standardowa odpowiedź dla HTMX
    async def generate_response():
        try:
            raw_response = await CopilotService.chat(llm_messages, profile, rok, miesiac, session_id=chat_session.id)
        except Exception as e:
            logger.exception("Błąd zapytania Copilota do silnika AI: %s", e)
            raw_response = (
                f"⚠️ **Błąd komunikacji z modelem AI:**\n\n"
                f"> {str(e)}\n\n"
                f"*Wskazówka:* Upewnij się, że w zakładce **Ustawienia** podano poprawny klucz API oraz prawidłową nazwę modelu."
            )
        log_ai_interaction(user_msg_clean, raw_response, nip=profile.nip if profile else None, okres=f"{rok}-{miesiac}")
        html_resp = markdown_to_html(raw_response)
        chat_session.update_message(record.id, html_resp, assistant_raw=raw_response, status="done")
        ChatSessionManager.save_session(profile, chat_session)
        CopilotSessionHistory.update_message(session_id, record.id, html_resp, status="done")
        return html_resp

    task = asyncio.create_task(generate_response())
    ChatSessionManager._running_tasks[chat_session.id] = task
    CopilotSessionHistory._running_tasks[session_id] = task

    title_bar_oob = render_session_title_bar(chat_session, oob=True)

    try:
        html_response = await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        return HTMLResponse(
            f"{render_user_bubble(user_msg_clean)}\n{render_assistant_bubble(html_response, record_id=record.id)}\n{title_bar_oob}",
            headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})},
        )
    except asyncio.TimeoutError:
        return HTMLResponse(
            f"{render_user_bubble(user_msg_clean)}\n{render_pending_bubble(record.id)}\n{title_bar_oob}",
            headers={"HX-Trigger": json.dumps({"copilot-refresh-sessions": True})},
        )
