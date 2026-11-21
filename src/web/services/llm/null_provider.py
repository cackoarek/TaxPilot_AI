"""
src/web/services/llm/null_provider.py
Fallback dla trybu Deterministycznego Zero-LLM (Graceful Degradation).
Zapewnia pomocne, regułowe odpowiedzi bez generowania halucynacji,
gdy aplikacja działa w środowisku bez skonfigurowanych kluczy LLM API.
"""

import asyncio
from typing import AsyncGenerator, List, Optional

from src.web.services.llm.base import BaseLLMProvider, ChatMessage


class NullProvider(BaseLLMProvider):
    """Deterministyczny dostawca Zero-LLM."""

    def __init__(self, model: str = "deterministic-zero-llm"):
        self._model = model

    @property
    def provider_name(self) -> str:
        return "null"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return False

    def _generate_deterministic_response(self, query: str) -> str:
        q = (query or "").lower()

        if any(w in q for w in ("rozlicz", "przegląd", "przeglad", "krok 2", "miesiąc", "miesiac")):
            return (
                "⚙️ **Tryb Deterministyczny:** Rozliczenie podatkowe za bieżący okres możesz przeprowadzić "
                "w module **[Wstępny Przegląd Dokumentów](/przeglad)**. Po akceptacji kosztów i przychodów "
                "silnik Pythona automatycznie wyliczy ZUS, ryczałt PIT-28 (12%) oraz bilans VAT-7."
            )
        elif any(w in q for w in ("aml", "biała lista", "biala lista", "kontrahent", "rachunek", "sankcje")):
            return (
                "🛡️ **Weryfikacja Kontrahentów:** Procedurę należytej staranności (Biała Lista VAT, sankcje MSWiA/UE, "
                "AML) możesz uruchomić bezpośrednio w **[Centrum Compliance & AML](/aml)**."
            )
        elif any(w in q for w in ("zus", "składki", "skladki", "zdrowotna", "nrs")):
            return (
                "📊 **Składki ZUS:** ZUS obliczany jest deterministycznie w oparciu o wskaźniki ustawowe (Duży ZUS / Mały ZUS / Ulga na Start) "
                "oraz progi przychodu dla składki zdrowotnej (do 60 tys., do 300 tys., pow. 300 tys. zł). "
                "Kod QR i numer konta NRS znajdziesz na Pulpicie głównym."
            )
        elif any(w in q for w in ("qr", "przelew", "paczka", "opłać", "oplac")):
            return (
                "📱 **Paczka Przelewów:** Kody QR zgodne ze standardem ZBP/Elixir wygenerujesz klikając przycisk "
                "„Pokaż Kod QR Przelewu” na kafelkach przelewów na **[Pulpicie](/)**."
            )
        else:
            return (
                "⚙️ **TaxPilot AI działa w trybie deterministycznym (Zero-LLM):**\n\n"
                "Wszystkie moduły księgowe, KSeF 2.0, weryfikacje AML, kalkulacje podatkowe i kody QR działają w 100% "
                "lokalnie w czystym Pythonie bez użycia zewnętrznych modeli sztucznej inteligencji.\n\n"
                "Aby odblokować konwersacyjnego asystenta AI, ustaw zmienną środowiskową "
                "`GEMINI_API_KEY`, `ANTHROPIC_API_KEY` lub `OPENAI_API_KEY`."
            )

    async def chat_async(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        last_query = messages[-1].content if messages else ""
        return self._generate_deterministic_response(last_query)

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> AsyncGenerator[str, None]:
        response_text = await self.chat_async(messages, system_prompt, temperature)
        # Symulacja płynnego strumieniowania
        words = response_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.015)
