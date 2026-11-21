"""
src/web/services/llm/antigravity_provider.py
Adapter dla lokalnego agenta AI uruchamianego za pomocą narzędzia Antigravity CLI ('agy').
Zapewnia interakcję z agentem w procesie Pythona w katalogu projektu,
inicjuje sesję z wymogiem zapoznania się z plikiem AGENTS.md oraz utrzymuje ciągłość sesji.
"""

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.logging_config import get_logger
from src.web.config import BASE_DIR, find_agy_binary
from src.web.services.llm.base import BaseLLMProvider, ChatMessage

logger = get_logger("taxpilot.llm.antigravity")

SYSTEM_AGENTS_INSTRUCTION = (
    "Pracujesz jako asystent podatkowo-księgowy TaxPilot AI w katalogu projektu. "
    "Koniecznie zaznajom się z plikiem AGENTS.md w bieżącym katalogu i bezwzględnie przestrzegaj "
    "zawartych w nim reguł architektonicznych, standardów workspace, Zero-Hallucination Policy "
    "(obliczenia wyłącznie deterministyczne przez Pythona Decimal) oraz ról dziedzinowych.\n\n"
    "BEZWZGLĘDNA IZOLACJA DANYCH FIRMY (MULTI-TENANT):\n"
    "- Wszystkie dane księgowe, faktury, koszty, przychody, ewidencje i rozliczenia analizujesz WYŁĄCZNIE w ramach firmy, w której zostałeś uruchomiony (wskazanej w sekcji [AKTYWNA FIRMA I WYBRANY OKRES ROZLICZENIOWY] w ścieżce: firmy/{NIP-Nazwa}/).\n"
    "- KATEGORYCZNY ZAKAZ: Zabrania się zaglądania do katalogów innych firm z folderu firmy/, odczytywania ich faktur, pobierania z nich danych oraz mieszania historii rozliczeń między firmami.\n\n"
    "KONTEKST INTERFEJSU WWW I FORMATOWANIE ODPOWIEDZI:\n"
    "- Twoje odpowiedzi są wyświetlane na żywo na stronie WWW w panelu bocznym czatu Copilota o ograniczonej szerokości (ok. 450px).\n"
    "- TABELE: Gdy prezentujesz zestawienia danych (np. podatki, składki ZUS, wykaz faktur, bilanse), twórz zwarte tabele w standardzie Markdown (maksymalnie 2-3 kolumny: np. | Pozycja | Kwota | Termin |). Zawsze stosuj pełny nagłówek i poprawny wiersz separatora (|---|---|---|), bez spacji przed pierwszą kreską pionową '|'. Silnik strony WWW automatycznie przekonwertuje je na estetyczne tabele HTML.\n"
    "- CZYTELNOŚĆ: Pisz zwięźle, dziel tekst na krótkie akapity, używaj punktorów dla list i pogrubień dla kluczowych kwot (np. **1 850,00 zł**).\n"
    "- NAWIGACJA: Podawaj przedsiębiorcy relatywne linki do ekranów aplikacji: [Pulpit](/), [Wstępny Przegląd](/przeglad), [Weryfikacja AML](/aml), [Doradca Podatkowy](/doradca), [Księgowanie](/ksiegowanie)."
)


class AntigravitySession:
    """
    Utrzymuje stan trwającej sesji z agentem Antigravity w katalogu projektu.
    Sesja jest powiązana z konkretną firmą (per wybrana firma) oraz śledzi
    aktualnie wybrany okres rozliczeniowy.
    """

    def __init__(
        self,
        session_id: str,
        cwd: Optional[Path] = None,
        company_nip: Optional[str] = None,
        company_name: Optional[str] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
        profile: Optional[Any] = None,
    ):
        self.session_id = session_id
        self.cwd = cwd or BASE_DIR
        self.company_nip = company_nip
        self.company_name = company_name
        self.current_period = f"{rok}-{miesiac}" if (rok and miesiac) else None
        self.profile = profile
        self.initialized = False
        self.conversation_id: Optional[str] = None
        self.turn_count = 0
        self.last_output: str = ""
        self.current_process: Optional[asyncio.subprocess.Process] = None
        self.created_at = time.time()
        self.last_used_at = time.time()
        self._lock = asyncio.Lock()

    def abort(self) -> None:
        """Przerywa aktualnie trwający proces jeśli istnieje."""
        if self.current_process and self.current_process.returncode is None:
            try:
                self.current_process.terminate()
                logger.info("Przerwano aktywny proces agy dla sesji %s", self.session_id)
            except Exception as e:
                logger.warning("Błąd przy przerywaniu procesu agy dla sesji %s: %s", self.session_id, e)
        self.current_process = None

    def update_context(
        self,
        profile: Optional[Any] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
    ) -> None:
        """Aktualizuje dane firmy i okresu w istniejącej sesji."""
        if profile is not None:
            self.profile = profile
            nip = getattr(profile, "nip", None) or (profile.get("nip") if isinstance(profile, dict) else None)
            nazwa = getattr(profile, "nazwa", None) or (profile.get("nazwa") if isinstance(profile, dict) else None)
            if nip:
                self.company_nip = nip
            if nazwa:
                self.company_name = nazwa

    def build_turn_prompt(
        self,
        user_content: str,
        system_prompt: Optional[str] = None,
        profile: Optional[Any] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
        history: Optional[str] = None,
    ) -> str:
        """Tworzy treść zapytania dla danej tury konwersacji."""
        parts = []

        # Przy pierwszej inicjacji sesji załącz nakaz zapoznania się z AGENTS.md oraz dane firmy i okresu
        if not self.initialized:
            if not self.session_id.startswith("extraction_"):
                parts.append(f"[INSTRUKCJA STARTOWA SYSTEMU]\n{SYSTEM_AGENTS_INSTRUCTION}\n")
            else:
                parts.append(
                    "[INSTRUKCJA EKSTRAKCJI DOKUMENTU]\nJesteś silnikiem ekstrakcji danych z faktur i paragonów TaxPilot AI. Odczytaj dane i zwróć WYŁĄCZNIE poprawny obiekt JSON zgodny ze strukturą, bez formatowania markdown i bez zbędnych komentarzy.\n"
                )

            active_profile = profile or self.profile
            cur_rok = rok or (self.current_period.split("-")[0] if self.current_period else None)
            cur_miesiac = miesiac or (self.current_period.split("-")[1] if self.current_period else None)

            context_info = []
            if active_profile:
                nazwa = getattr(active_profile, "nazwa", None) or (
                    active_profile.get("nazwa") if isinstance(active_profile, dict) else "N/A"
                )
                nip = getattr(active_profile, "nip", None) or (
                    active_profile.get("nip") if isinstance(active_profile, dict) else "N/A"
                )
                context_info.append(f"- Aktywna firma: {nazwa} (NIP: {nip})")

                forma = getattr(active_profile, "forma_opodatkowania", None)
                if forma:
                    forma_val = forma.value if hasattr(forma, "value") else str(forma)
                    stawka = getattr(active_profile, "domyslna_stawka_ryczaltu", None)
                    stawka_str = f" (stawka: {stawka * 100:.0f}%)" if stawka else ""
                    context_info.append(f"- Forma opodatkowania: {forma_val}{stawka_str}")

                if hasattr(active_profile, "platnik_vat"):
                    context_info.append(f"- Płatnik VAT: {'TAK' if active_profile.platnik_vat else 'NIE'}")

                zus = getattr(active_profile, "zus", None)
                if zus and hasattr(zus, "typ"):
                    zus_val = zus.typ.value if hasattr(zus.typ, "value") else str(zus.typ)
                    context_info.append(f"- ZUS: {zus_val}")

                folder_name = getattr(active_profile, "folder_name", None)
                if not folder_name and nip:
                    clean_name = str(nazwa).replace(" ", "_")
                    folder_name = f"{nip}-{clean_name}"
                if folder_name:
                    context_info.append(f"- Ścieżka danych firmy: firmy/{folder_name}/")
                    context_info.append(
                        f"- ZASADA IZOLACJI: Analizujesz dane księgowe, faktury i rozliczenia WYŁĄCZNIE z katalogu firmy/{folder_name}/. Zabrania się analizowania danych innych firm."
                    )
            elif self.company_nip:
                context_info.append(f"- Aktywna firma: {self.company_name or 'JDG'} (NIP: {self.company_nip})")

            if cur_rok and cur_miesiac:
                period_str = f"{cur_rok}-{cur_miesiac}"
                self.current_period = period_str
                context_info.append(f"- Domyślnie wybrany okres rozliczeniowy: {period_str}")

            if context_info:
                parts.append("[AKTYWNA FIRMA I WYBRANY OKRES ROZLICZENIOWY]\n" + "\n".join(context_info) + "\n")

            if system_prompt:
                parts.append(f"[KONTEKST PODATNIKA]\n{system_prompt}\n")
            self.initialized = True
        else:
            # W kolejnych turach sprawdź czy okres nie uległ zmianie
            new_period = f"{rok}-{miesiac}" if (rok and miesiac) else None
            if new_period and self.current_period and new_period != self.current_period:
                parts.append(
                    f"[ZMIANA WYBRANEGO OKRESU ROZLICZENIOWEGO] Aktualnie wybrany okres został zmieniony na: {new_period}\n"
                )
                self.current_period = new_period
            elif system_prompt and self.turn_count == 0:
                parts.append(f"[KONTEKST PODATNIKA]\n{system_prompt}\n")

        if not parts and not history:
            return user_content

        if history:
            parts.append(f"[HISTORIA DIALOGU W TEJ SESJI]\n{history}\n")

        parts.append(f"[ZAPYTANIE UŻYTKOWNIKA]\n{user_content}")
        return "\n".join(parts)


class AntigravitySessionManager:
    """Zarządca aktywnych sesji Antigravity w pamięci procesu (sesja per wybrana firma)."""

    _instances: Dict[str, AntigravitySession] = {}

    @classmethod
    def get_or_create_session(
        cls,
        session_id: str = "default",
        cwd: Optional[Path] = None,
        profile: Optional[Any] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
    ) -> AntigravitySession:
        if session_id not in cls._instances:
            company_nip = getattr(profile, "nip", None) or (profile.get("nip") if isinstance(profile, dict) else None)
            company_name = getattr(profile, "nazwa", None) or (
                profile.get("nazwa") if isinstance(profile, dict) else None
            )
            cls._instances[session_id] = AntigravitySession(
                session_id=session_id,
                cwd=cwd,
                company_nip=company_nip,
                company_name=company_name,
                rok=rok,
                miesiac=miesiac,
                profile=profile,
            )
            logger.info(
                "Zainicjowano nową sesję Antigravity dla firmy/sesji: %s (NIP: %s, okres: %s-%s)",
                session_id,
                company_nip,
                rok,
                miesiac,
            )
        else:
            session = cls._instances[session_id]
            session.update_context(profile=profile, rok=rok, miesiac=miesiac)
        return cls._instances[session_id]

    @classmethod
    def reset_session(cls, session_id: str = "default") -> None:
        if session_id in cls._instances:
            session = cls._instances[session_id]
            session.abort()
            del cls._instances[session_id]
            logger.info("Zresetowano sesję Antigravity: %s", session_id)

    @classmethod
    def reset_all(cls) -> None:
        for session in cls._instances.values():
            session.abort()
        cls._instances.clear()
        logger.info("Zresetowano wszystkie sesje Antigravity")

    @classmethod
    def get_last_output(cls, session_id: str = "default") -> str:
        session = cls._instances.get(session_id)
        return session.last_output if session else ""


class AntigravityProvider(BaseLLMProvider):
    """
    Dostawca LLM integrujący narzędzie CLI Antigravity ('agy').
    Wywołuje agenta w procesie Pythona na katalogu projektu z podtrzymywaniem sesji per firma.
    """

    def __init__(
        self,
        binary_path: Optional[str] = None,
        model: Optional[str] = None,
        session_id: str = "default",
        cwd: Optional[Path] = None,
        profile: Optional[Any] = None,
        rok: Optional[str] = None,
        miesiac: Optional[str] = None,
    ):
        self._binary_path = binary_path or find_agy_binary() or "agy"
        self._model = (model or os.getenv("TAXPILOT_LLM_MODEL") or "antigravity-cli").strip()
        self._session_id = session_id
        self._cwd = cwd or BASE_DIR
        self._profile = profile
        self._rok = rok
        self._miesiac = miesiac

    @property
    def provider_name(self) -> str:
        return "antigravity"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        """Sprawdza czy binarz 'agy' jest dostępny i wykonywalny."""
        resolved = shutil.which(self._binary_path)
        if resolved:
            return True
        p = Path(self._binary_path)
        return p.exists() and os.access(p, os.X_OK)

    def _prepare_env(self) -> Dict[str, str]:
        """Przygotowuje zmienne środowiskowe dla procesu 'agy'."""
        env = dict(os.environ)
        # Upewnij się, że standardowe ścieżki CLI są w PATH
        home_bin = str(Path.home() / ".local" / "bin")
        current_path = env.get("PATH", "")
        if home_bin not in current_path:
            env["PATH"] = f"{home_bin}:{current_path}"
        return env

    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """Wysyła zapytanie do sesji agenta Antigravity i zwraca odpowiedź tekstową."""
        if not self.is_configured():
            return (
                "⚠️ **Błąd konfiguracji Antigravity CLI:** Nie znaleziono binarza `agy` w systemie. "
                "Upewnij się, że Antigravity CLI jest zainstalowane w `~/.local/bin/agy` lub dostępne w PATH."
            )

        session = AntigravitySessionManager.get_or_create_session(
            session_id=self._session_id,
            cwd=self._cwd,
            profile=self._profile,
            rok=self._rok,
            miesiac=self._miesiac,
        )

        last_user_msg = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m.content
                break

        if not last_user_msg:
            return "Brak zapytania użytkownika."

        history_parts = []
        for m in messages[:-1]:
            role = "Użytkownik" if m.role == "user" else "Asystent"
            history_parts.append(f"{role}: {m.content}")
        history_str = "\n".join(history_parts) if history_parts else None

        async with session._lock:
            prompt_payload = session.build_turn_prompt(
                last_user_msg,
                system_prompt=system_prompt,
                profile=self._profile,
                rok=self._rok,
                miesiac=self._miesiac,
                history=history_str,
            )

            cmd = [
                self._binary_path,
                "-p",
                prompt_payload,
                "--output-format",
                "text",
                "--dangerously-skip-permissions",
            ]
            if self._model and self._model not in ("antigravity-cli", "gemini-3.8-flash"):
                cmd.extend(["--model", self._model])

            # Jeśli sesja miała już wcześniejsze tury z przypisanym conversation_id, wskaż id konwersacji, w p.p. --continue
            if session.turn_count > 0 and not session.session_id.startswith("extraction_"):
                if session.conversation_id:
                    cmd.extend(["--conversation", session.conversation_id])
                else:
                    cmd.append("--continue")

            if session.session_id.startswith("extraction_"):
                logger.info(
                    "Uruchamianie komendy agy w katalogu %s (turn=%d, timeout=75s)", self._cwd, session.turn_count
                )
            else:
                logger.info(
                    "Uruchamianie komendy agy w katalogu %s (turn=%d, bez limitu timeout dla czatu)",
                    self._cwd,
                    session.turn_count,
                )
            env = self._prepare_env()

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._cwd),
                    env=env,
                )
                session.current_process = proc
                if session.session_id.startswith("extraction_"):
                    stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=75.0)
                else:
                    # Dla czatu Copilota model ma nielimitowany czas na generowanie odpowiedzi.
                    # W razie potrzeby użytkownik może zresetować sesję przyciskiem "Nowa sesja".
                    stdout_data, stderr_data = await proc.communicate()
            except asyncio.CancelledError:
                session.abort()
                raise
            except Exception as e:
                logger.exception("Błąd uruchomienia procesu agy: %s", e)
                last_out = session.last_output
                err_msg = [f"⚠️ **Błąd wykonania procesu agy:** {e}"]
                if last_out:
                    err_msg.append(f"\n\n**Ostatnie wyjście modelu:**\n\n```\n{last_out}\n```")
                err_msg.append(
                    "\n\n*Wskazówka:* Jeśli sesja uległa zawieszeniu, kliknij przycisk **🔄 Nowa sesja** w nagłówku czatu."
                )
                return "".join(err_msg)
            finally:
                session.current_process = None

            session.turn_count += 1
            session.last_used_at = time.time()

            stdout_text = stdout_data.decode("utf-8", errors="replace").strip()
            stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
            session.last_output = stdout_text

            if proc.returncode != 0:
                logger.warning("Proces agy zakończony kodem %d: %s", proc.returncode, stderr_text)
                if stdout_text:
                    return f"{stdout_text}\n\n*(Uwaga: proces agy zakończył się kodem {proc.returncode})*"
                return (
                    f"⚠️ **Antigravity CLI zwrócił błąd (kod {proc.returncode}):**\n\n"
                    f"```\n{stderr_text[:500] if stderr_text else 'Brak szczegółów błędu'}\n```\n\n"
                    f"*Wskazówka:* Uruchom `agy` bezpośrednio w terminalu w katalogu `{self._cwd}`, aby zweryfikować uprawnienia."
                )

            return stdout_text or "Agent zakończył zadanie bez odpowiedzi tekstowej."

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        """Strumieniuje odpowiedź w czasie rzeczywistym z procesu agenta Antigravity bez limitu czasu."""
        if not self.is_configured():
            yield (
                "⚠️ **Błąd konfiguracji Antigravity CLI:** Nie znaleziono binarza `agy` w systemie. "
                "Upewnij się, że Antigravity CLI jest zainstalowane w `~/.local/bin/agy` lub dostępne w PATH."
            )
            return

        session = AntigravitySessionManager.get_or_create_session(
            session_id=self._session_id,
            cwd=self._cwd,
            profile=self._profile,
            rok=self._rok,
            miesiac=self._miesiac,
        )

        last_user_msg = ""
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m.content
                break

        if not last_user_msg:
            yield "Brak zapytania użytkownika."
            return

        history_parts = []
        for m in messages[:-1]:
            role = "Użytkownik" if m.role == "user" else "Asystent"
            history_parts.append(f"{role}: {m.content}")
        history_str = "\n".join(history_parts) if history_parts else None

        async with session._lock:
            prompt_payload = session.build_turn_prompt(
                last_user_msg,
                system_prompt=system_prompt,
                profile=self._profile,
                rok=self._rok,
                miesiac=self._miesiac,
                history=history_str,
            )

            cmd = [self._binary_path, "-p", prompt_payload, "--output-format", "text"]
            if self._model and self._model != "antigravity-cli":
                cmd.extend(["--model", self._model])

            if session.turn_count > 0:
                if session.conversation_id:
                    cmd.extend(["--conversation", session.conversation_id])
                else:
                    cmd.append("--continue")

            logger.info(
                "Uruchamianie streamingu agy w katalogu %s (turn=%d, bez limitu timeout)", self._cwd, session.turn_count
            )
            env = self._prepare_env()

            accumulated = []
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._cwd),
                    env=env,
                )
                session.current_process = proc

                # Czytanie wiersz po wierszu na żywo z procesu
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    decoded_line = line.decode("utf-8", errors="replace")
                    accumulated.append(decoded_line)
                    session.last_output = "".join(accumulated)
                    yield decoded_line

                await proc.wait()
                session.turn_count += 1
                session.last_used_at = time.time()

                if proc.returncode != 0:
                    stderr_bytes = await proc.stderr.read()
                    stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
                    logger.warning("Proces agy zakończony kodem %d: %s", proc.returncode, stderr_text)
                    if not accumulated and stderr_text:
                        yield (
                            f"\n\n⚠️ **Antigravity CLI zwrócił błąd (kod {proc.returncode}):**\n"
                            f"```\n{stderr_text[:500]}\n```"
                        )
            except asyncio.CancelledError:
                logger.info("Anulowano strumieniowanie agy dla sesji: %s", session.session_id)
                session.abort()
                raise
            except Exception as e:
                logger.exception("Błąd w trakcie streamingu agy: %s", e)
                last_out = session.last_output
                yield f"\n\n⚠️ **Wystąpił błąd procesu agy:** {e}\n"
                if last_out:
                    yield f"\n**Ostatnie odebrane wyjście z modelu:**\n\n```\n{last_out}\n```\n"
                yield "\n*Wskazówka:* Możesz zresetować sesję przyciskiem **🔄 Nowa sesja** w nagłówku czatu."
            finally:
                session.current_process = None
