"""
src/web/routers/copilot.py
Kontroler asystenta AI Copilot (SSE Streaming & HTMX chat).
"""
import re
import json
from typing import Optional, List
from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.web.config import TEMPLATES_DIR, get_llm_status
from src.web.dependencies import get_global_context
from src.web.services.llm.base import ChatMessage
from src.web.services.copilot_service import CopilotService

router = APIRouter(prefix="/api/copilot", tags=["AI Copilot"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def markdown_to_html(text: str) -> str:
    """Prosty konwerter markdown na bezpieczny kod HTML dla dymków czatu."""
    if not text:
        return ""
    # Pogrubienia **tekst**
    formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Linki [tekst](url)
    formatted = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" class="text-blue-600 underline font-semibold hover:text-blue-800">\1</a>',
        formatted
    )
    # Formatowanie akapitów i list
    paragraphs = formatted.split("\n\n")
    out = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        lines = p.split("\n")
        in_list = False
        p_html = []
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("- ") or line_str.startswith("* "):
                if not in_list:
                    p_html.append('<ul class="list-disc pl-4 space-y-1 my-1">')
                    in_list = True
                p_html.append(f"<li>{line_str[2:]}</li>")
            else:
                if in_list:
                    p_html.append("</ul>")
                    in_list = False
                p_html.append(f"<p class='mb-1.5'>{line_str}</p>")
        if in_list:
            p_html.append("</ul>")
        out.append("".join(p_html))
    return "".join(out)


@router.get("/status")
async def copilot_status():
    """Zwraca aktualny stan dostępności i konfiguracji modeli LLM."""
    return get_llm_status()


@router.post("/chat", response_class=HTMLResponse)
async def copilot_chat(
    request: Request,
    message: str = Form(...),
    stream: bool = Query(False),
):
    """
    Endpoint obsługujący zapytania do asystenta AI Copilot.
    Wspiera standardowe żądania HTMX (zwracając dymki HTML) oraz SSE streaming.
    """
    ctx = get_global_context(request)
    profile = ctx["profile"]
    rok = ctx["rok"]
    miesiac = ctx["miesiac"]

    user_msg_clean = message.strip()
    if not user_msg_clean:
        raise HTTPException(status_code=400, detail="Wiadomość nie może być pusta.")

    messages = [ChatMessage(role="user", content=user_msg_clean)]

    # Obsługa SSE Streaming jeśli klient zażąda streamingu
    accept_header = request.headers.get("accept", "")
    if stream or "text/event-stream" in accept_header:
        async def event_generator():
            async for token in CopilotService.stream_chat(messages, profile, rok, miesiac):
                yield f"data: {json.dumps({'delta': token})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Standardowa odpowiedź dla HTMX
    raw_response = await CopilotService.chat(messages, profile, rok, miesiac)
    html_response = markdown_to_html(raw_response)

    bubble_ctx = {
        "request": request,
        "user_message": user_msg_clean,
        "assistant_message": html_response,
    }
    return templates.TemplateResponse(request=request, name="partials/copilot_message.html", context=bubble_ctx)
