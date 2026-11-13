"""
src/web/services/copilot_service.py
Serwis AI Copilota integrujący kontekst finansowo-podatkowy firmy z warstwą LLM.
Przestrzega reguły Zero-Hallucination: nie liczy podatków w pamięci,
lecz prezentuje deterministyczne wyliczenia silnika Python.
"""
from typing import List, Optional, AsyncGenerator, Dict, Any

from src.core.company import CompanyProfile
from src.web.services.llm.base import BaseLLMProvider, ChatMessage
from src.web.services.llm.factory import LLMProviderFactory
from src.web.routers.dashboard import load_settlement_data, load_aml_stats


class CopilotService:
    """Orkiestrator asystenta AI dla przedsiębiorcy."""

    @classmethod
    def build_system_prompt(
        cls,
        profile: Optional[CompanyProfile],
        rok: str,
        miesiac: str,
    ) -> str:
        """Buduje prompt systemowy z kontekstem firmy i rozliczenia."""
        if not profile:
            return (
                "Jesteś asystentem TaxPilot AI. Pomagasz przedsiębiorcom w prowadzeniu JDG w Polsce, "
                "rozliczeniach KSeF 2.0, weryfikacji AML oraz procedurze należytej staranności."
            )

        settlement = load_settlement_data(profile, rok, miesiac)
        aml_stats = load_aml_stats(profile, rok, miesiac)

        context_lines = [
            "Jesteś asystentem AI w systemie księgowym TaxPilot AI dla jednoosobowej działalności gospodarczej (JDG).",
            f"Firma: {profile.nazwa} (NIP: {profile.nip})",
            f"Forma opodatkowania: {profile.forma_opodatkowania.value} (stawka domyślna: {profile.domyslna_stawka_ryczaltu * 100:.0f}%)",
            f"Płatnik VAT: {'TAK' if profile.platnik_vat else 'NIE'}",
            f"ZUS: {profile.zus.typ.value}",
            f"Aktualnie przeglądany okres rozliczeniowy: {rok}-{miesiac}",
        ]

        if settlement:
            pit = settlement.get("pit28", {}).get("zaliczka_pit28_zaokraglona", "0")
            vat = settlement.get("vat", {}).get("vat_do_zaplaty_zaokraglony", "0")
            zus = settlement.get("zus", {}).get("lacznie_do_zaplaty", "0")
            przychod = (
                settlement.get("ewidencja", {})
                .get("ewidencja_przychodow", {})
                .get("laczny_przychod_netto", "0")
            )
            context_lines.extend([
                f"Status rozliczenia za {rok}-{miesiac}: SFINALIZOWANE (Rozliczone)",
                f"- Przychody netto: {przychod} zł",
                f"- Zaliczka PIT-28: {pit} zł (termin: 20. następnego miesiąca)",
                f"- VAT-7 do zapłaty: {vat} zł (termin: 25. następnego miesiąca)",
                f"- ZUS łącznie: {zus} zł (termin: 20. następnego miesiąca)",
                f"- Mikrorachunek podatkowy US: 10 1010 0055 0225 {profile.nip} 000",
                f"- Rachunek NRS ZUS: 83 1010 1023 0000 26{profile.nip}",
            ])
        else:
            context_lines.append(
                f"Status rozliczenia za {rok}-{miesiac}: W TRAKCIE (wymaga weryfikacji w Krok 2: /przeglad)"
            )

        if aml_stats:
            context_lines.append(
                f"Compliance AML: zweryfikowano {aml_stats.get('liczba_kontrahentow', 0)} kontrahentów."
            )

        context_lines.extend([
            "",
            "ZASADY ODPOWIADANIA (BEZWZGLĘDNE):",
            "1. Zero-Hallucination: Nigdy nie licz podatków ani ZUS 'w pamięci'. Wszystkie liczby muszą pochodzić z powyższego kontekstu.",
            "2. Wskazuj przedsiębiorcy linki do ekranów: Pulpit (/), Wstępny Przegląd (/przeglad), Weryfikacja AML (/aml), Doradca (/doradca).",
            "3. Odpowiadaj zwięźle, konkretnie, uprzejmie i profesjonalnie w języku polskim w formacie Markdown.",
        ])

        return "\n".join(context_lines)

    @classmethod
    async def chat(
        cls,
        messages: List[ChatMessage],
        profile: Optional[CompanyProfile],
        rok: str,
        miesiac: str,
        provider_override: Optional[str] = None,
    ) -> str:
        """Generuje pełną odpowiedź asystenta."""
        provider = LLMProviderFactory.get_provider(profile=profile, provider_override=provider_override)
        system_prompt = cls.build_system_prompt(profile, rok, miesiac)
        return await provider.chat_async(messages, system_prompt=system_prompt)

    @classmethod
    async def stream_chat(
        cls,
        messages: List[ChatMessage],
        profile: Optional[CompanyProfile],
        rok: str,
        miesiac: str,
        provider_override: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Strumieniuje odpowiedź asystenta token po tokenie."""
        provider = LLMProviderFactory.get_provider(profile=profile, provider_override=provider_override)
        system_prompt = cls.build_system_prompt(profile, rok, miesiac)
        async for chunk in provider.stream_chat(messages, system_prompt=system_prompt):
            yield chunk
