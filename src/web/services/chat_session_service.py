"""
src/web/services/chat_session_service.py
Serwis zarządzania trwałymi sesjami rozmów asystenta AI Copilot w TaxPilot AI.
Wspiera przechowywanie historii per firma (Multi-Tenant), nadawanie i edycję tytułów,
wybór i wznawianie starszych rozmów oraz pełny kontekst wieloturowy dla modeli LLM.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import time
import uuid

from src.core.company import CompanyProfile
from src.config import FIRMY_DIR
from src.logging_config import get_logger

logger = get_logger("taxpilot.chat_sessions")


@dataclass
class ChatMessageRecord:
    id: str
    user_message: str
    assistant_message: str  # Renderowany HTML
    assistant_raw: str = ""  # Surowy markdown do wysłania do LLM w kolejnych turach
    status: str = "done"  # "pending", "done", "error"
    created_at: str = ""
    created_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_message": self.user_message,
            "assistant_message": self.assistant_message,
            "assistant_raw": self.assistant_raw,
            "status": self.status,
            "created_at": self.created_at,
            "created_timestamp": self.created_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessageRecord":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            user_message=data.get("user_message", ""),
            assistant_message=data.get("assistant_message", ""),
            assistant_raw=data.get("assistant_raw", ""),
            status=data.get("status", "done"),
            created_at=data.get("created_at", ""),
            created_timestamp=data.get("created_timestamp", time.time()),
        )


@dataclass
class ChatSession:
    id: str
    title: str
    created_at: str
    updated_at: str
    nip: str = "default"
    rok: str = "2026"
    miesiac: str = "01"
    messages: List[ChatMessageRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "nip": self.nip,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "messages": [m.to_dict() for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        messages = [ChatMessageRecord.from_dict(m) for m in data.get("messages", [])]
        return cls(
            id=data.get("id", ""),
            title=data.get("title", "Nowa rozmowa"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            nip=data.get("nip", "default"),
            rok=data.get("rok", "2026"),
            miesiac=data.get("miesiac", "01"),
            messages=messages,
        )

    def add_user_message(self, user_msg: str) -> ChatMessageRecord:
        msg_id = str(uuid.uuid4())[:8]
        record = ChatMessageRecord(
            id=msg_id,
            user_message=user_msg,
            assistant_message="",
            assistant_raw="",
            status="pending",
            created_at=datetime.now().strftime("%H:%M:%S"),
            created_timestamp=time.time(),
        )
        self.messages.append(record)
        self.updated_at = datetime.now().isoformat()
        # Jeśli tytuł jest domyślny, wygeneruj czytelny tytuł z pierwszej wypowiedzi
        if self.title in ("Nowa rozmowa", "Rozmowa bez nazwy", "", "Nowa sesja"):
            cleaned = " ".join(user_msg.strip().split())
            if len(cleaned) > 42:
                self.title = cleaned[:40].rstrip() + "..."
            else:
                self.title = cleaned or "Nowa rozmowa"
        return record

    def update_message(self, record_id: str, assistant_html: str, assistant_raw: str = "", status: str = "done"):
        for r in self.messages:
            if r.id == record_id:
                r.assistant_message = assistant_html
                if assistant_raw:
                    r.assistant_raw = assistant_raw
                r.status = status
                self.updated_at = datetime.now().isoformat()
                break

    def get_message_by_id(self, record_id: str) -> Optional[ChatMessageRecord]:
        for r in self.messages:
            if r.id == record_id:
                return r
        return None


class ChatSessionManager:
    """Zarządca trwałych sesji czatu na dysku w katalogu firmy (Multi-Tenant)."""
    _active_sessions_cache: Dict[str, str] = {}  # nip -> active_session_id
    _sessions_cache: Dict[str, ChatSession] = {}  # session_id -> ChatSession
    _running_tasks: Dict[str, Any] = {}  # session_id -> asyncio.Task

    @staticmethod
    def get_sessions_dir(profile: Optional[CompanyProfile]) -> Path:
        if profile and hasattr(profile, "katalog_firmy") and profile.katalog_firmy:
            d = profile.katalog_firmy / "chat_sessions"
        else:
            d = FIRMY_DIR / "default" / "chat_sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def list_sessions(cls, profile: Optional[CompanyProfile]) -> List[Dict[str, Any]]:
        s_dir = cls.get_sessions_dir(profile)
        sessions = []
        for p in s_dir.glob("session_*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    messages = data.get("messages", [])
                    # Podgląd ostatniej wiadomości
                    last_snippet = ""
                    if messages:
                        last_msg = messages[-1]
                        last_snippet = last_msg.get("user_message", "") or ""
                        if len(last_snippet) > 60:
                            last_snippet = last_snippet[:57] + "..."

                    created_str = data.get("created_at", "")
                    # Formatowanie czytelnej daty
                    display_date = created_str
                    try:
                        dt = datetime.fromisoformat(created_str)
                        display_date = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        pass

                    sessions.append({
                        "id": data.get("id"),
                        "title": data.get("title", "Rozmowa"),
                        "created_at": created_str,
                        "display_date": display_date,
                        "updated_at": data.get("updated_at", ""),
                        "rok": data.get("rok", "2026"),
                        "miesiac": data.get("miesiac", "01"),
                        "messages_count": len(messages),
                        "snippet": last_snippet,
                    })
            except Exception as e:
                logger.warning("Błąd odczytu sesji czatu z %s: %s", p, e)

        # Sortowanie od najnowszych
        sessions.sort(key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True)
        return sessions

    @classmethod
    def get_active_session(
        cls,
        profile: Optional[CompanyProfile],
        rok: str = "2026",
        miesiac: str = "01",
        create_if_none: bool = True
    ) -> Optional[ChatSession]:
        nip = profile.nip if profile else "default"
        s_dir = cls.get_sessions_dir(profile)
        active_id = cls._active_sessions_cache.get(nip)

        active_file = s_dir / "active_session.txt"
        if not active_id and active_file.exists():
            try:
                saved_id = active_file.read_text(encoding="utf-8").strip()
                if saved_id:
                    active_id = saved_id
            except Exception:
                pass

        if active_id:
            session = cls.load_session(profile, active_id)
            if session:
                cls._active_sessions_cache[nip] = session.id
                return session

        # Jeśli brak aktywnej sesji, poszukaj najnowszej na dysku
        sessions = cls.list_sessions(profile)
        if sessions:
            latest_id = sessions[0]["id"]
            session = cls.load_session(profile, latest_id)
            if session:
                cls.set_active_session_id(profile, session.id)
                return session

        # Jeśli brak jakichkolwiek sesji, utwórz nową
        if create_if_none:
            return cls.create_new_session(profile, rok=rok, miesiac=miesiac)
        return None

    @classmethod
    def set_active_session_id(cls, profile: Optional[CompanyProfile], session_id: str):
        nip = profile.nip if profile else "default"
        cls._active_sessions_cache[nip] = session_id
        try:
            s_dir = cls.get_sessions_dir(profile)
            (s_dir / "active_session.txt").write_text(session_id, encoding="utf-8")
        except Exception as e:
            logger.warning("Nie udało się zapisać active_session.txt: %s", e)

    @classmethod
    def load_session(cls, profile: Optional[CompanyProfile], session_id: str) -> Optional[ChatSession]:
        if session_id in cls._sessions_cache:
            return cls._sessions_cache[session_id]

        s_dir = cls.get_sessions_dir(profile)
        session_file = s_dir / f"{session_id}.json"
        if not session_file.exists():
            matches = list(s_dir.glob(f"*{session_id}*.json"))
            if matches:
                session_file = matches[0]
            else:
                return None

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = ChatSession.from_dict(data)
            cls._sessions_cache[session.id] = session
            return session
        except Exception as e:
            logger.error("Błąd ładowania sesji %s: %s", session_id, e)
            return None

    @classmethod
    def save_session(cls, profile: Optional[CompanyProfile], session: ChatSession):
        cls._sessions_cache[session.id] = session
        s_dir = cls.get_sessions_dir(profile)
        session_file = s_dir / f"{session.id}.json"
        try:
            tmp_file = s_dir / f"{session.id}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
            tmp_file.replace(session_file)
        except Exception as e:
            logger.error("Błąd zapisu sesji %s: %s", session.id, e)

    @classmethod
    def create_new_session(
        cls,
        profile: Optional[CompanyProfile],
        rok: str = "2026",
        miesiac: str = "01",
        title: str = "Nowa rozmowa"
    ) -> ChatSession:
        nip = profile.nip if profile else "default"
        now = datetime.now()
        ts_id = now.strftime("%Y%m%d_%H%M%S")
        rand_suffix = str(uuid.uuid4())[:6]
        session_id = f"session_{ts_id}_{rand_suffix}"

        session = ChatSession(
            id=session_id,
            title=title,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            nip=nip,
            rok=rok,
            miesiac=miesiac,
            messages=[],
        )
        cls.save_session(profile, session)
        cls.set_active_session_id(profile, session.id)
        return session

    @classmethod
    def rename_session(cls, profile: Optional[CompanyProfile], session_id: str, new_title: str) -> bool:
        session = cls.load_session(profile, session_id)
        if not session:
            return False
        clean_title = new_title.strip()
        if not clean_title:
            clean_title = "Rozmowa bez nazwy"
        session.title = clean_title
        session.updated_at = datetime.now().isoformat()
        cls.save_session(profile, session)
        return True

    @classmethod
    def delete_session(cls, profile: Optional[CompanyProfile], session_id: str) -> bool:
        nip = profile.nip if profile else "default"
        s_dir = cls.get_sessions_dir(profile)
        session_file = s_dir / f"{session_id}.json"

        if session_id in cls._running_tasks:
            t = cls._running_tasks[session_id]
            if not t.done():
                t.cancel()
            del cls._running_tasks[session_id]

        if session_id in cls._sessions_cache:
            del cls._sessions_cache[session_id]

        deleted = False
        if session_file.exists():
            try:
                session_file.unlink()
                deleted = True
            except Exception as e:
                logger.error("Błąd usuwania pliku sesji %s: %s", session_file, e)

        if cls._active_sessions_cache.get(nip) == session_id:
            cls._active_sessions_cache.pop(nip, None)
            sessions = cls.list_sessions(profile)
            if sessions:
                cls.set_active_session_id(profile, sessions[0]["id"])
            else:
                active_file = s_dir / "active_session.txt"
                if active_file.exists():
                    try:
                        active_file.unlink()
                    except Exception:
                        pass
        return deleted
