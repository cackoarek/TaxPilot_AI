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
                "rozliczeniach KSeF 2.0, weryfikacji AML oraz procedurze należytej staranności. "
                "Analizuj dane finansowo-księgowe wyłącznie w ramach aktywnej firmy, w której zostałeś uruchomiony."
            )

        settlement = load_settlement_data(profile, rok, miesiac)
        aml_stats = load_aml_stats(profile, rok, miesiac)

        folder_name = getattr(profile, "folder_name", None)
        if not folder_name and profile.nip:
            clean_name = str(profile.nazwa).replace(" ", "_")
            folder_name = f"{profile.nip}-{clean_name}"
        company_folder_str = f"firmy/{folder_name}/" if folder_name else f"firmy/{profile.nip}/"

        context_lines = [
            "Jesteś asystentem AI w systemie księgowym TaxPilot AI dla jednoosobowej działalności gospodarczej (JDG).",
            f"Firma: {profile.nazwa} (NIP: {profile.nip})",
            f"Katalog roboczy firmy: {company_folder_str}",
            f"Forma opodatkowania: {profile.forma_opodatkowania.value} (stawka domyślna: {profile.domyslna_stawka_ryczaltu * 100:.0f}%)",
            f"Płatnik VAT: {'TAK' if profile.platnik_vat else 'NIE'}",
            f"ZUS: {profile.zus.typ.value}",
            f"Aktualnie przeglądany okres rozliczeniowy: {rok}-{miesiac}",
            "",
            "BEZWZGLĘDNA IZOLACJA DANYCH FIRMY (MULTI-TENANT):",
            f"- Twoim bezwzględnym obowiązkiem jest analizowanie danych finansowych, faktur, kosztów, przychodów i rozliczeń WYŁĄCZNIE w ramach firmy, w której zostałeś uruchomiony: {profile.nazwa} (NIP: {profile.nip}) w jej dedykowanym katalogu: {company_folder_str}.",
            "- KATEGORYCZNY ZAKAZ: Pod żadnym pozorem nie odczytuj, nie analizuj, nie ujawniaj ani nie mieszaj danych z katalogów innych firm znajdujących się w folderze firmy/. Jeśli użytkownik pyta o stan rozliczeń, koszty lub przychody, odpowiadasz wyłącznie w oparciu o dokumenty i stan tej jednej aktywnej firmy.",
            "",
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
            "ZASADY ODPOWIADANIA I FORMATOWANIA DLA STRONY WWW (BEZWZGLĘDNE):",
            "1. ŚRODOWISKO WYŚWIETLANIA: Rozmowa jest wyświetlana na żywo na stronie WWW w bocznym oknie czatu Copilota o ograniczonej szerokości (ok. 450px).",
            "2. Zero-Hallucination: Nigdy nie licz podatków ani ZUS 'w pamięci'. Wszystkie liczby muszą pochodzić z powyższego kontekstu.",
            "3. TABELE DLA STRONY WWW: Gdy prezentujesz zestawienia kwot, terminów lub faktur, twórz zwarte tabele w standardzie Markdown (maksymalnie 2-3 kolumny: np. | Pozycja | Kwota | Termin |) z pełnym wierszem nagłówka i separatora (|---|---|---|). Nie wstawiaj spacji przed pierwszą kreską '|'. Silnik strony WWW automatycznie przekształca je na estetyczne, responsywne tabele HTML.",
            "4. LINKI W SYSTEMIE: Wskazuj przedsiębiorcy linki do ekranów: [Pulpit](/), [Wstępny Przegląd](/przeglad), [Weryfikacja AML](/aml), [Doradca Podatkowy](/doradca), [Księgowanie](/ksiegowanie).",
            "5. CZYTELNOŚĆ: Odpowiadaj zwięźle, dziel tekst na krótkie akapity, używaj punktorów dla list i pogrubień dla kluczowych liczb (np. **1 850,00 zł**).",
            f"6. IZOLACJA FIRMY: Pod żadnym pozorem nie odnoś się do danych innych podmiotów. Cała analiza dotyczy wyłącznie aktywnej firmy: {profile.nazwa} (NIP: {profile.nip}) w jej katalogu {company_folder_str}.",
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
        session_id: Optional[str] = None,
    ) -> str:
        """Generuje pełną odpowiedź asystenta."""
        provider = LLMProviderFactory.get_provider(
            profile=profile,
            provider_override=provider_override,
            rok=rok,
            miesiac=miesiac,
            session_id=session_id,
        )
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
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Strumieniuje odpowiedź asystenta token po tokenie."""
        provider = LLMProviderFactory.get_provider(
            profile=profile,
            provider_override=provider_override,
            rok=rok,
            miesiac=miesiac,
            session_id=session_id,
        )
        system_prompt = cls.build_system_prompt(profile, rok, miesiac)
        async for chunk in provider.stream_chat(messages, system_prompt=system_prompt):
            yield chunk
