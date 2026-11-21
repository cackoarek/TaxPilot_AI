"""
src/web/services/ai_cost_qualifier.py
Moduł asynchronicznej kwalifikacji pozycji kosztowych z wykorzystaniem silnika AI (LLM)
oraz reguł eksperckich prawa podatkowego (PIT / VAT).
Działa w tle z możliwością swobodnej nawigacji użytkownika między zakładkami w UI.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.logging_config import get_logger
from src.skills.cost_classifier import (
    CostClassifier,
    KwalifikacjaKosztu,
    RegulyKosztoweFirmy,
)
from src.web.services.llm.base import ChatMessage
from src.web.services.llm.factory import LLMProviderFactory

logger = get_logger("taxpilot.ai_qualifier")


@dataclass
class AIQualificationItem:
    numer_faktury: str
    sprzedawca_nazwa: str
    sprzedawca_nip: str
    pozycja_opis: str
    kwota_netto: Decimal
    kwota_vat: Decimal
    kwalifikacja_sugerowana: str  # FIRMOWY_100 | SAMOCHOD_50 | PRYWATNY_0
    porada_ksiegowa: str
    zatwierdzony: bool = False
    data_utworzenia: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer_faktury": self.numer_faktury,
            "sprzedawca_nazwa": self.sprzedawca_nazwa,
            "sprzedawca_nip": self.sprzedawca_nip,
            "pozycja_opis": self.pozycja_opis,
            "kwota_netto": str(self.kwota_netto),
            "kwota_vat": str(self.kwota_vat),
            "kwalifikacja_sugerowana": self.kwalifikacja_sugerowana,
            "porada_ksiegowa": self.porada_ksiegowa,
            "zatwierdzony": self.zatwierdzony,
            "data_utworzenia": self.data_utworzenia,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AIQualificationItem":
        return cls(
            numer_faktury=d.get("numer_faktury", ""),
            sprzedawca_nazwa=d.get("sprzedawca_nazwa", ""),
            sprzedawca_nip=d.get("sprzedawca_nip", ""),
            pozycja_opis=d.get("pozycja_opis", ""),
            kwota_netto=Decimal(str(d.get("kwota_netto", "0.00"))),
            kwota_vat=Decimal(str(d.get("kwota_vat", "0.00"))),
            kwalifikacja_sugerowana=d.get("kwalifikacja_sugerowana", "FIRMOWY_100"),
            porada_ksiegowa=d.get("porada_ksiegowa", ""),
            zatwierdzony=bool(d.get("zatwierdzony", False)),
            data_utworzenia=d.get("data_utworzenia", ""),
        )


class AICostQualifierService:
    """Zarządca procesu kwalifikacji pozycji kosztowych AI i pamięci podręcznej porad."""

    # Pamięć stanów procesów w tle: key -> dict
    _task_states: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def _get_key(cls, nip: str, rok: str, miesiac: str) -> str:
        clean_nip = re.sub(r"[^0-9]", "", nip)
        return f"{clean_nip}_{rok}_{str(miesiac).zfill(2)}"

    @classmethod
    def _storage_path(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        m_str = str(miesiac).zfill(2)
        dir_path = profile.katalog_firmy / "rozliczenia" / str(rok) / m_str
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / ".ai_kwalifikacje.json"

    @classmethod
    def load_suggestions(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Dict[str, AIQualificationItem]:
        """Wczytuje zapisane sugestie AI dla danego miesiąca z dysku."""
        path = cls._storage_path(profile, rok, miesiac)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: AIQualificationItem.from_dict(v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Błąd odczytu .ai_kwalifikacje.json: %s", e)
            return {}

    @classmethod
    def save_suggestions(
        cls, profile: CompanyProfile, rok: str, miesiac: str, suggestions: Dict[str, AIQualificationItem]
    ):
        """Zapisuje sugestie AI na dysku."""
        path = cls._storage_path(profile, rok, miesiac)
        try:
            raw = {k: v.to_dict() for k, v in suggestions.items()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Błąd zapisu .ai_kwalifikacje.json: %s", e)

    @classmethod
    def get_status(cls, nip: str, rok: str, miesiac: str) -> Dict[str, Any]:
        """Zwraca aktualny stan zadania w tle."""
        key = cls._get_key(nip, rok, miesiac)
        state = cls._task_states.get(key)
        if not state:
            return {"status": "idle", "message": "", "progress_pct": 0, "total": 0, "current": 0}
        return state

    @classmethod
    def set_status(
        cls,
        nip: str,
        rok: str,
        miesiac: str,
        status: str,
        message: str,
        current: int = 0,
        total: int = 0,
        error: Optional[str] = None,
    ):
        key = cls._get_key(nip, rok, miesiac)
        pct = int((current / total * 100)) if total > 0 else 0
        cls._task_states[key] = {
            "status": status,
            "message": message,
            "progress_pct": pct,
            "current": current,
            "total": total,
            "error": error,
            "updated_at": datetime.now().isoformat(),
        }

    @classmethod
    def approve_item(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        numer_faktury: str,
        pozycja_opis: str,
        kwalifikacja: str,
        save_as_rule: bool = True,
    ) -> bool:
        """
        Zatwierdza sugestię AI dla danej pozycji:
        - Zapisuje trwałą regułę w reguly_kosztowe.json
        - Oznacza w .ai_kwalifikacje.json jako zatwierdzoną
        """
        suggestions = cls.load_suggestions(profile, rok, miesiac)
        item_key = f"{numer_faktury.strip()}::{pozycja_opis.strip().lower()}"

        # Pobierz dane kontrahenta
        faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
        inv = next((i for i in faktury if i.numer == numer_faktury or i.numer.strip() == numer_faktury.strip()), None)
        seller_nip = inv.sprzedawca.nip if inv and inv.sprzedawca else None

        if save_as_rule:
            reguly = RegulyKosztoweFirmy.load(profile)
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=pozycja_opis.strip(),
                kwalifikacja=KwalifikacjaKosztu(kwalifikacja),
                uzasadnienie="Zatwierdzono przez przedsiębiorcę w UI (Sugestia AI)",
                nip_kontrahenta=seller_nip,
            )
            reguly.save(profile)
            logger.info(
                "Utrwalono regułę po zatwierdzeniu AI: '%s' -> %s (NIP: %s)", pozycja_opis, kwalifikacja, seller_nip
            )

        # Oznacz w pamięci sugestii
        if item_key in suggestions:
            suggestions[item_key].zatwierdzony = True
            suggestions[item_key].kwalifikacja_sugerowana = kwalifikacja
            cls.save_suggestions(profile, rok, miesiac, suggestions)
        else:
            # Utwórz zatwierdzony wpis
            suggestions[item_key] = AIQualificationItem(
                numer_faktury=numer_faktury,
                sprzedawca_nazwa=inv.sprzedawca.nazwa if inv and inv.sprzedawca else "",
                sprzedawca_nip=seller_nip or "",
                pozycja_opis=pozycja_opis,
                kwota_netto=Decimal("0.00"),
                kwota_vat=Decimal("0.00"),
                kwalifikacja_sugerowana=kwalifikacja,
                porada_ksiegowa="Pozycja zatwierdzona przez przedsiębiorcę.",
                zatwierdzony=True,
            )
            cls.save_suggestions(profile, rok, miesiac, suggestions)

        return True

    @classmethod
    def approve_bulk_items(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        numer_faktury: str,
        pozycje_opisy: List[str],
        kwalifikacja: str,
    ) -> bool:
        """
        Zatwierdza sugestie AI dla wszystkich pozycji wskazanej faktury w jednym zapisie.
        Nie tworzy automatycznie reguł stałych (pozostaje jako decyzja okresowa).
        """
        suggestions = cls.load_suggestions(profile, rok, miesiac)
        num_clean = numer_faktury.strip()

        faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
        inv = next((i for i in faktury if i.numer == numer_faktury or i.numer.strip() == num_clean), None)
        seller_nip = inv.sprzedawca.nip if inv and inv.sprzedawca else ""
        seller_nazwa = inv.sprzedawca.nazwa if inv and inv.sprzedawca else ""

        for pozycja_opis in pozycje_opisy:
            if not pozycja_opis or not pozycja_opis.strip():
                continue
            item_key = f"{num_clean}::{pozycja_opis.strip().lower()}"
            if item_key in suggestions:
                suggestions[item_key].zatwierdzony = True
                suggestions[item_key].kwalifikacja_sugerowana = kwalifikacja
            else:
                suggestions[item_key] = AIQualificationItem(
                    numer_faktury=num_clean,
                    sprzedawca_nazwa=seller_nazwa,
                    sprzedawca_nip=seller_nip,
                    pozycja_opis=pozycja_opis.strip(),
                    kwota_netto=Decimal("0.00"),
                    kwota_vat=Decimal("0.00"),
                    kwalifikacja_sugerowana=kwalifikacja,
                    porada_ksiegowa="Pozycja zatwierdzona przez przedsiębiorcę (zbiorczo).",
                    zatwierdzony=True,
                )

        cls.save_suggestions(profile, rok, miesiac, suggestions)
        return True

    @classmethod
    async def start_ai_qualification(cls, profile: CompanyProfile, rok: str, miesiac: str) -> None:
        """Uruchamia zadanie asynchroniczne kwalifikacji pozycji kosztowych."""
        key = cls._get_key(profile.nip, rok, miesiac)
        curr = cls._task_states.get(key, {})
        if curr.get("status") == "running":
            logger.info("Kwalifikacja AI już trwa dla %s %s-%s", profile.nazwa, rok, miesiac)
            return

        cls.set_status(profile.nip, rok, miesiac, "running", "Inicjalizacja modelu AI i analiza pozycji...", 0, 1)
        asyncio.create_task(cls._execute_qualification(profile, rok, miesiac))

    @classmethod
    async def _execute_qualification(cls, profile: CompanyProfile, rok: str, miesiac: str) -> None:
        """Pętla wykonawcza kwalifikacji AI."""
        nip = profile.nip
        try:
            logger.info(
                "Rozpoczęto analizę AI pozycji faktur kosztowych dla firmy %s (%s-%s)", profile.nazwa, rok, miesiac
            )
            faktury = InvoiceStorage.list_invoices(profile, rok, miesiac, typ=InvoiceType.KOSZT)
            reguly_firmy = RegulyKosztoweFirmy.load(profile)
            existing_suggestions = cls.load_suggestions(profile, rok, miesiac)

            # Wyodrębnij pozycje do zakwalifikowania (te, które nie mają sztywnej reguły kontrahenta)
            pozycje_do_analizy = []
            for inv in faktury:
                seller_nip = re.sub(r"[^0-9]", "", inv.sprzedawca.nip) if inv.sprzedawca else ""
                for p in inv.pozycje:
                    p.opis.strip().lower()
                    # Sprawdź, czy pozycja ma już stałą regułę kontrahenta
                    has_rule = False
                    if seller_nip in reguly_firmy.reguly_kontrahentow:
                        matched = CostClassifier._find_best_matching_rule(
                            reguly_firmy.reguly_kontrahentow[seller_nip], p.opis
                        )
                        if matched:
                            has_rule = True
                    if not has_rule:
                        matched_glob = CostClassifier._find_best_matching_rule(reguly_firmy.reguly_globalne, p.opis)
                        if matched_glob:
                            has_rule = True
                    if not has_rule:
                        pozycje_do_analizy.append((inv, p))

            total = len(pozycje_do_analizy)
            if total == 0:
                cls.set_status(
                    nip,
                    rok,
                    miesiac,
                    "completed",
                    "Wszystkie pozycje posiadają już zapamiętane reguły podatkowe.",
                    1,
                    1,
                )
                return

            cls.set_status(
                nip, rok, miesiac, "running", f"Przygotowano {total} pozycji do kwalifikacji AI...", 0, total
            )

            # Pobierz providera LLM
            llm_provider = LLMProviderFactory.get_provider(profile=profile, rok=rok, miesiac=miesiac)
            kody_pkd_str = (
                ", ".join(profile.kody_pkd)
                if profile.kody_pkd
                else "62.01.Z, 62.02.Z (Działalność programistyczna i IT)"
            )

            for idx, (inv, pos) in enumerate(pozycje_do_analizy, start=1):
                item_key = f"{inv.numer.strip()}::{pos.opis.strip().lower()}"

                # Jeśli pozycja została już wcześniej zatwierdzona przez użytkownika w tym miesiącu, pomiń
                if item_key in existing_suggestions and existing_suggestions[item_key].zatwierdzony:
                    continue

                cls.set_status(
                    nip,
                    rok,
                    miesiac,
                    "running",
                    f"Kwalifikacja AI [{idx}/{total}]: {pos.opis[:35]}... ({inv.sprzedawca.nazwa[:25] if inv.sprzedawca else ''})",
                    idx - 1,
                    total,
                )

                kwalifikacja, porada = await cls._classify_single_item(
                    llm_provider=llm_provider,
                    item=pos,
                    inv=inv,
                    kody_pkd_str=kody_pkd_str,
                    profile_nazwa=profile.nazwa,
                )

                # Zapisz sugestię
                existing_suggestions[item_key] = AIQualificationItem(
                    numer_faktury=inv.numer,
                    sprzedawca_nazwa=inv.sprzedawca.nazwa if inv.sprzedawca else "",
                    sprzedawca_nip=inv.sprzedawca.nip if inv.sprzedawca else "",
                    pozycja_opis=pos.opis,
                    kwota_netto=pos.wartosc_netto,
                    kwota_vat=pos.kwota_vat,
                    kwalifikacja_sugerowana=kwalifikacja,
                    porada_ksiegowa=porada,
                    zatwierdzony=False,
                )
                cls.save_suggestions(profile, rok, miesiac, existing_suggestions)

            cls.set_status(
                nip,
                rok,
                miesiac,
                "completed",
                f"Zakończono kwalifikację AI. Przeanalizowano {total} pozycji faktur. Sprawdź porady księgowe i zatwierdź pozycje.",
                total,
                total,
            )
            logger.info("Ukończono pomyślnie kwalifikację AI dla %s (%s-%s)", profile.nazwa, rok, miesiac)

        except Exception as e:
            logger.exception("Błąd w procesie kwalifikacji AI: %s", e)
            cls.set_status(
                nip, rok, miesiac, "error", f"Wystąpił błąd podczas analizy AI: {str(e)}", 0, 0, error=str(e)
            )

    @classmethod
    async def _classify_single_item(
        cls,
        llm_provider,
        item,
        inv: Invoice,
        kody_pkd_str: str,
        profile_nazwa: str,
    ) -> Tuple[str, str]:
        """Wywołuje LLM z promptem doradcy podatkowego lub fallback ekspercki."""
        desc = item.opis.strip()
        seller_nazwa = inv.sprzedawca.nazwa if inv.sprzedawca else "Sprzedawca"
        seller_nip = inv.sprzedawca.nip if inv.sprzedawca else ""
        netto = f"{item.wartosc_netto:.2f} zł"

        system_prompt = (
            "Jesteś Certyfikowanym Głównym Księgowym i Biegłym Rewidentem w polskim systemie podatkowym. "
            "Twoim zadaniem jest ocena pojedynczej pozycji z faktury kosztowej dla jednoosobowej działalności gospodarczej (JDG). "
            f"Firma klienta: '{profile_nazwa}', PKD: {kody_pkd_str}. "
            "Musisz zakwalifikować pozycję do jednej z trzech kategorii:\n"
            "1. 'FIRMOWY_100' - wydatek firmowy związany z prowadzoną działalnością, dający prawo do pełnego odliczenia 100% VAT i KUP (art. 22 ust. 1 PIT, art. 86 ust. 1 VAT).\n"
            "2. 'SAMOCHOD_50' - wydatek na eksploatację samochodu osobowego w trybie mieszanym (art. 86a VAT, 50% VAT / 75% KUP - np. paliwo, myjnia, serwis, parking).\n"
            "3. 'PRYWATNY_0' - wydatek o charakterze osobistym lub niebędący kosztem firmy (art. 23 ust. 1 PIT - np. pakiety medyczne rodzinne, TV osobiste, zabawki, prywatne zakupy spożywcze).\n\n"
            "Odpowiedz WYŁĄCZNIE poprawnym obiektem JSON w formacie:\n"
            '{"kwalifikacja": "FIRMOWY_100" | "SAMOCHOD_50" | "PRYWATNY_0", "porada": "Krótka, konkretna porada księgowa (maksymalnie 2-3 zdania) wyjaśniająca przedsiębiorcy, dlaczego taka kwalifikacja jest właściwa i wskazująca przepis prawa."}'
        )

        user_content = (
            f"Faktura: {inv.numer}\n"
            f"Sprzedawca: {seller_nazwa} (NIP: {seller_nip})\n"
            f"Pozycja z faktury: {desc}\n"
            f"Wartość netto: {netto}\n"
            "Podaj kwalifikację podatkową oraz poradę księgową w JSON."
        )

        # 1. Próba wywołania LLM
        if llm_provider and llm_provider.is_configured():
            try:
                raw_response = await asyncio.wait_for(
                    llm_provider.chat_async(
                        messages=[ChatMessage(role="user", content=user_content)],
                        system_prompt=system_prompt,
                        temperature=0.1,
                    ),
                    timeout=20.0,
                )
                # Parsowanie JSON z odpowiedzi
                m = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    kwal = parsed.get("kwalifikacja", "FIRMOWY_100").strip().upper()
                    porada = parsed.get("porada", "").strip()
                    if kwal not in ("FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"):
                        kwal = "FIRMOWY_100"
                    if porada:
                        return kwal, porada
            except Exception as ex:
                logger.warning(
                    "Wywołanie LLM dla pozycji '%s' nie powiodło się (%s), przejście na reguły eksperckie.", desc, ex
                )

        # 2. Heurystyka ekspercka (Fallback wysokiej jakości)
        desc_l = desc.lower()
        if any(
            w in desc_l
            for w in [
                "paliwo",
                "benzyn",
                "diesel",
                "lpg",
                "efecta",
                "myjnia",
                "wulkanizacj",
                "opon",
                "serwis auta",
                "parking",
                "autostrad",
            ]
        ):
            return (
                "SAMOCHOD_50",
                "Eksploatacja pojazdu osobowego w trybie mieszanym. Zgodnie z art. 86a ustawy o VAT przysługuje 50% odliczenia VAT, a w podatku dochodowym 75% zaliczenia do KUP.",
            )

        if any(
            w in desc_l
            for w in [
                "tv",
                "telewizj",
                "pakiet tv",
                "vod",
                "netflix",
                "rodzinn",
                "zabawk",
                "lego",
                "kosmetyk",
                "fryzjer",
            ]
        ):
            return (
                "PRYWATNY_0",
                "Wydatek ma charakter osobisty (art. 23 ust. 1 ustawy o PIT). Organy podatkowe kwestionują zaliczenie do kosztów firmy – rekomendowane 0% VAT i wyłączenie z KUP.",
            )

        if any(w in desc_l for w in ["stół", "biurk", "krzesł", "catering", "fotele", "mebl"]):
            return (
                "FIRMOWY_100",
                "Wyposażenie stanowiska pracy / biura. Wydatek ma bezpośredni związek z organizacją i funkcjonowaniem przedsiębiorstwa (art. 22 ust. 1 PIT) – pełne 100% VAT.",
            )

        if any(
            w in desc_l
            for w in [
                "komputer",
                "laptop",
                "monitor",
                "kamera",
                "klawiatur",
                "mysz",
                "serwer",
                "hosting",
                "cloud",
                "internet",
                "telefon",
            ]
        ):
            return (
                "FIRMOWY_100",
                f"Sprzęt i usługi IT bezpośrednio wspierające profil działalności ({kody_pkd_str[:15]}). Zgodnie z art. 86 ust. 1 VAT przysługuje pełne prawo do odliczenia 100% podatku.",
            )

        return (
            "FIRMOWY_100",
            "Standardowy wydatek operacyjny na cele prowadzonej działalności gospodarczej (art. 22 ust. 1 ustawy o PIT). Przysługuje pełne 100% odliczenia VAT.",
        )
