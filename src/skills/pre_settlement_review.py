"""
Moduł weryfikacji i audytu dokumentów przed ostatecznym rozliczeniem podatkowym (Pre-settlement Review).
Generuje deterministyczne zestawienia:
1. Faktury przychodowe (sprzedaż) – do zaznajomienia się i weryfikacji kompletności.
2. Faktury kosztowe (zakupy) – do weryfikacji przynależności i akceptacji przez przedsiębiorcę.
3. Pozycje i faktury do wyjaśnienia – pozycje niejednoznaczne (DO_WYJASNIENIA) oraz wykluczenia prywatne (PRYWATNY_0).
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_deduplicator import DuplicateAnomaly, DuplicateType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.skills.aml_tools import AMLVerificationEngine
from src.skills.cost_classifier import (
    CostClassifier,
    KwalifikacjaKosztu,
    ReczneKwalifikacjeService,
    RegulyKosztoweFirmy,
    audit_invoice_expense,
)
from src.skills.ryczalt_tools import RegulySprzedazyFirmy


@dataclass
class SalesItemReview:
    """Pozycja faktury sprzedaży w zestawieniu przychodów."""

    lp: int
    data: str
    numer: str
    nabywca_nazwa: str
    nabywca_nip: str
    przedmiot: str
    kwota_netto: Decimal
    stawka_ryczaltu: Decimal
    kwota_vat: Decimal
    kwota_brutto: Decimal
    zrodlo: str = "KSeF"
    status_aml: str = "🟢 Czysty"
    pozycje: List[Dict[str, Any]] = field(default_factory=list)
    pelny_przedmiot: str = ""
    plik_zrodlowy: Optional[str] = None
    ksef_numer_referencyjny: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "zrodlo": self.zrodlo,
            "data": self.data,
            "numer": self.numer,
            "nabywca_nazwa": self.nabywca_nazwa,
            "nabywca_nip": self.nabywca_nip,
            "przedmiot": self.przedmiot,
            "pelny_przedmiot": self.pelny_przedmiot or self.przedmiot,
            "kwota_netto": str(self.kwota_netto),
            "stawka_ryczaltu": str(self.stawka_ryczaltu),
            "kwota_vat": str(self.kwota_vat),
            "kwota_brutto": str(self.kwota_brutto),
            "status_aml": self.status_aml,
            "pozycje": self.pozycje,
            "plik_zrodlowy": self.plik_zrodlowy,
            "ksef_numer_referencyjny": self.ksef_numer_referencyjny,
        }


@dataclass
class ExpenseItemReview:
    """Faktura kosztowa w zestawieniu zakupów do weryfikacji przez przedsiębiorcę."""

    lp: int
    data: str
    numer: str
    sprzedawca_nazwa: str
    sprzedawca_nip: str
    glowny_przedmiot: str
    kwota_netto: Decimal
    kwota_vat: Decimal
    kwota_brutto: Decimal
    kwalifikacja_podatkowa: str
    status_weryfikacji: str
    zrodlo: str = "KSeF"
    status_aml: str = "🟢 Czysty"
    pozycje: List[Dict[str, Any]] = field(default_factory=list)
    kwalifikowany_vat: Decimal = Decimal("0.00")
    kwalifikowane_netto: Decimal = Decimal("0.00")
    odrzucony_vat_prywatny: Decimal = Decimal("0.00")
    odrzucone_netto_prywatne: Decimal = Decimal("0.00")
    zasadnosc_opis: str = ""
    ai_sugestia: Optional[str] = None
    ai_porada: Optional[str] = None
    wymaga_zatwierdzenia: bool = False
    zatwierdzony: bool = False
    plik_zrodlowy: Optional[str] = None
    ksef_numer_referencyjny: Optional[str] = None
    kwalifikacja_kod: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "zrodlo": self.zrodlo,
            "data": self.data,
            "numer": self.numer,
            "sprzedawca_nazwa": self.sprzedawca_nazwa,
            "sprzedawca_nip": self.sprzedawca_nip,
            "glowny_przedmiot": self.glowny_przedmiot,
            "kwota_netto": str(self.kwota_netto),
            "kwota_vat": str(self.kwota_vat),
            "kwota_brutto": str(self.kwota_brutto),
            "kwalifikacja_podatkowa": self.kwalifikacja_podatkowa,
            "kwalifikacja_kod": self.kwalifikacja_kod,
            "status_weryfikacji": self.status_weryfikacji,
            "status_aml": self.status_aml,
            "pozycje": self.pozycje,
            "kwalifikowany_vat": str(self.kwalifikowany_vat),
            "kwalifikowane_netto": str(self.kwalifikowane_netto),
            "odrzucony_vat_prywatny": str(self.odrzucony_vat_prywatny),
            "odrzucone_netto_prywatne": str(self.odrzucone_netto_prywatne),
            "zasadnosc_opis": self.zasadnosc_opis,
            "ai_sugestia": self.ai_sugestia,
            "ai_porada": self.ai_porada,
            "wymaga_zatwierdzenia": self.wymaga_zatwierdzenia,
            "zatwierdzony": self.zatwierdzony,
            "plik_zrodlowy": self.plik_zrodlowy,
            "ksef_numer_referencyjny": self.ksef_numer_referencyjny,
        }


@dataclass
class ClarificationItemReview:
    """Pozycja kosztowa wymagająca wyjaśnienia lub zatwierdzenia przez przedsiębiorcę."""

    lp: int
    numer_faktury: str
    kontrahent_nazwa: str
    kontrahent_nip: str
    pozycja_opis: str
    kwota_netto: Decimal
    kwota_vat: Decimal
    status: str
    uzasadnienie: str
    pytanie_do_uzytkownika: str
    sugerowana_odpowiedz: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "numer_faktury": self.numer_faktury,
            "kontrahent_nazwa": self.kontrahent_nazwa,
            "kontrahent_nip": self.kontrahent_nip,
            "pozycja_opis": self.pozycja_opis,
            "kwota_netto": str(self.kwota_netto),
            "kwota_vat": str(self.kwota_vat),
            "status": self.status,
            "uzasadnienie": self.uzasadnienie,
            "pytanie_do_uzytkownika": self.pytanie_do_uzytkownika,
            "sugerowana_odpowiedz": self.sugerowana_odpowiedz,
        }


@dataclass
class PreSettlementReview:
    """Kompletny raport weryfikacyjny przed ostatecznym rozliczeniem miesiąca."""

    profil: CompanyProfile
    rok: str
    miesiac: str
    sprzedaz: List[SalesItemReview] = field(default_factory=list)
    koszty: List[ExpenseItemReview] = field(default_factory=list)
    do_wyjasnienia: List[ClarificationItemReview] = field(default_factory=list)
    duplikaty: List[DuplicateAnomaly] = field(default_factory=list)
    relokacje: List[Dict[str, Any]] = field(default_factory=list)
    laczna_sprzedaz_netto: Decimal = Decimal("0.00")
    laczna_sprzedaz_vat: Decimal = Decimal("0.00")
    laczna_sprzedaz_brutto: Decimal = Decimal("0.00")
    laczny_koszt_netto: Decimal = Decimal("0.00")
    laczny_koszt_vat: Decimal = Decimal("0.00")
    laczny_koszt_brutto: Decimal = Decimal("0.00")
    ostrzezenie_sieci_aml: bool = False

    @property
    def laczny_kwalifikowany_vat(self) -> Decimal:
        """Suma VAT podlegająca faktycznemu odliczeniu po uwzględnieniu stawek 100%, 50% i 0%."""
        return sum((item.kwalifikowany_vat for item in self.koszty), Decimal("0.00"))

    @property
    def laczne_kwalifikowane_netto(self) -> Decimal:
        """Koszty netto kwalifikujące się do KUP."""
        return sum((item.kwalifikowane_netto for item in self.koszty), Decimal("0.00"))

    @property
    def laczny_odrzucony_vat_prywatny(self) -> Decimal:
        """Suma VAT wykluczona z odliczenia (wydatki osobiste/prywatne)."""
        return sum((item.odrzucony_vat_prywatny for item in self.koszty), Decimal("0.00"))

    @property
    def laczne_odrzucone_netto_prywatne(self) -> Decimal:
        """Suma netto wykluczona z KUP."""
        return sum((item.odrzucone_netto_prywatne for item in self.koszty), Decimal("0.00"))

    @classmethod
    def build(cls, profile: CompanyProfile, rok: str, miesiac: str) -> "PreSettlementReview":
        """Tworzy deterministyczny raport przeglądu dokumentów za podany miesiąc."""
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        # 1. Automatyczna ekstrakcja dokumentów spoza KSeF (sprzedaż i koszty) z non-ksef-raw/ do non-ksef-extracted/
        NonKSeFExtractor.extract_all(profile, rok_str, miesiac_str)

        # 2. Wykrycie potencjalnych duplikatów i kolizji źródłowych
        duplikaty = InvoiceStorage.get_duplicate_anomalies(profile, rok_str, miesiac_str)

        # 2. Faktury sprzedaży (z uwzględnieniem korekt wstecznych dla PIT)
        reguly_sprzedazy = RegulySprzedazyFirmy.load(profile)
        faktury_sprzedaz = InvoiceStorage.list_sales_invoices_for_pit(profile=profile, rok=rok_str, miesiac=miesiac_str)
        domyslna_stawka_ryczaltu = Decimal(str(profile.domyslna_stawka_ryczaltu))

        sales_items: List[SalesItemReview] = []
        suma_sprzedaz_netto = Decimal("0.00")
        suma_sprzedaz_vat = Decimal("0.00")
        suma_sprzedaz_brutto = Decimal("0.00")

        # Pamięć podręczna weryfikacji sankcyjnej w ramach przeglądu (jeden kontrahent sprawdzany dokładnie 1 raz)
        kontrahent_aml_cache: Dict[str, str] = {}
        wykryto_blad_sieci_aml = False

        def get_contractor_aml_status(c_nip: str, c_nazwa: str) -> str:
            nonlocal wykryto_blad_sieci_aml
            clean = re.sub(r"[^0-9]", "", c_nip)
            if clean in kontrahent_aml_cache:
                return kontrahent_aml_cache[clean]

            # Sprawdzenie w trwałym cache AML firmy
            cached = AMLVerificationEngine.get_cached_contractor(clean, profile=profile)
            if cached:
                if cached.sankcje_mswia or cached.sankcje_ue:
                    res = "🚨 STOP (Sankcje)"
                elif cached.blad_polaczenia:
                    res = "⚠️ Błąd sieci (Offline)"
                    wykryto_blad_sieci_aml = True
                elif not cached.platnik_vat_czynny:
                    res = "⚠️ Sprawdź VAT"
                else:
                    res = "🟢 Czysty"
            else:
                # Nie uruchamiamy audytu live AML w module przeglądu – od tego jest dedykowany widok AML
                res = "⚪ Nie weryfikowano"

            kontrahent_aml_cache[clean] = res
            return res

        for idx, inv in enumerate(faktury_sprzedaz, start=1):
            pelny_przedmiot = ", ".join([p.opis for p in inv.pozycje]) if inv.pozycje else "Usługi IT"
            przedmiot = pelny_przedmiot
            if len(przedmiot) > 55:
                przedmiot = przedmiot[:52] + "..."

            buyer_stawka = None
            if inv.pozycje and inv.pozycje[0].stawka_ryczaltu is not None:
                buyer_stawka = inv.pozycje[0].stawka_ryczaltu
            else:
                buyer_stawka = reguly_sprzedazy.stawki_nabywcow.get(inv.nabywca.nip, domyslna_stawka_ryczaltu)

            zrodlo_val = "Non-KSeF" if getattr(inv, "zrodlo", "") == "NON_KSEF" else "KSeF"

            # Weryfikacja sankcyjna z cache (jeden kontrahent sprawdzany 1 raz)
            status_aml = get_contractor_aml_status(inv.nabywca.nip, inv.nabywca.nazwa)

            pozycje_sprzedaz = []
            for p_idx, p in enumerate(inv.pozycje, start=1):
                pozycje_sprzedaz.append(
                    {
                        "lp": p_idx,
                        "opis": p.opis,
                        "ilosc": str(p.ilosc),
                        "jednostka": p.jednostka,
                        "cena_jednostkowa_netto": p.cena_jednostkowa_netto,
                        "wartosc_netto": p.wartosc_netto,
                        "stawka_vat": p.stawka_vat,
                        "kwota_vat": p.kwota_vat,
                        "wartosc_brutto": p.wartosc_brutto,
                        "stawka_ryczaltu": str(buyer_stawka),
                    }
                )

            sales_items.append(
                SalesItemReview(
                    lp=idx,
                    data=inv.data_wystawienia,
                    numer=inv.numer,
                    nabywca_nazwa=inv.nabywca.nazwa,
                    nabywca_nip=inv.nabywca.nip,
                    przedmiot=przedmiot,
                    pelny_przedmiot=pelny_przedmiot,
                    kwota_netto=inv.suma_netto,
                    stawka_ryczaltu=buyer_stawka,
                    kwota_vat=inv.suma_vat,
                    kwota_brutto=inv.suma_brutto,
                    zrodlo=zrodlo_val,
                    status_aml=status_aml,
                    pozycje=pozycje_sprzedaz,
                    plik_zrodlowy=inv.plik_zrodlowy,
                    ksef_numer_referencyjny=inv.ksef_numer_referencyjny,
                )
            )
            suma_sprzedaz_netto += inv.suma_netto
            if inv.okres_rozliczeniowy == (rok_str, miesiac_str):
                suma_sprzedaz_vat += inv.suma_vat
                suma_sprzedaz_brutto += inv.suma_brutto
            else:
                # Korekta wsteczna dla celów PIT rozlicza VAT w miesiącu wystawienia (art. 29a ust. 13 VAT)
                suma_sprzedaz_brutto += inv.suma_netto

        # 3. Faktury kosztowe i audyt
        faktury_koszt = InvoiceStorage.list_invoices(
            profile=profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.KOSZT
        )
        reguly_firmy = RegulyKosztoweFirmy.load(profile)
        reczne_overrides = ReczneKwalifikacjeService.load_overrides(profile, rok_str, miesiac_str)

        from src.web.services.ai_cost_qualifier import AICostQualifierService

        ai_sugestie = AICostQualifierService.load_suggestions(profile, rok_str, miesiac_str)

        expense_items: List[ExpenseItemReview] = []
        clarification_items: List[ClarificationItemReview] = []
        suma_koszt_netto = Decimal("0.00")
        suma_koszt_vat = Decimal("0.00")
        suma_koszt_brutto = Decimal("0.00")

        clarification_idx = 1
        for idx, inv in enumerate(faktury_koszt, start=1):
            audit = audit_invoice_expense(
                inv,
                reguly_firmy,
                kody_pkd=profile.kody_pkd,
                reczne_overrides=reczne_overrides,
            )
            opis_glowny = ", ".join([p.opis for p in inv.pozycje[:3]]) if inv.pozycje else "Zakup towarów/usług"
            if len(opis_glowny) > 50:
                opis_glowny = opis_glowny[:47] + "..."

            # Ocena kwalifikacji ogólnej faktury
            kwalifikacje = [p.kwalifikacja for p in audit.pozycje_wyniki]
            if any(k == KwalifikacjaKosztu.DO_WYJASNIENIA for k in kwalifikacje):
                kwal_tekst = "⚠️ Wymaga wyjaśnienia"
                status_tekst = "Wymaga decyzji"
                kwal_kod = "DO_WYJASNIENIA"
            elif any(k == KwalifikacjaKosztu.PRYWATNY_0 for k in kwalifikacje) and any(
                k == KwalifikacjaKosztu.FIRMOWY_100 for k in kwalifikacje
            ):
                kwal_tekst = "Mieszana (wykluczenia prywatne)"
                status_tekst = "Do akceptacji"
                kwal_kod = "MIESZANA"
            elif all(k == KwalifikacjaKosztu.PRYWATNY_0 for k in kwalifikacje):
                kwal_tekst = "⛔ Prywatny (0% VAT/KUP)"
                status_tekst = "Wykluczona"
                kwal_kod = "PRYWATNY_0"
            elif all(k == KwalifikacjaKosztu.SAMOCHOD_50 for k in kwalifikacje):
                kwal_tekst = "🚗 Samochód 50% (art. 86a)"
                status_tekst = "Do akceptacji"
                kwal_kod = "SAMOCHOD_50"
            elif all(k == KwalifikacjaKosztu.FIRMOWY_100 for k in kwalifikacje):
                kwal_tekst = "✅ 100% Firmowy"
                status_tekst = "Do akceptacji"
                kwal_kod = "FIRMOWY_100"
            else:
                kwal_tekst = "Częściowo odliczalny"
                status_tekst = "Do akceptacji"
                kwal_kod = "MIESZANA"

            zrodlo_val = "Non-KSeF" if getattr(inv, "zrodlo", "") == "NON_KSEF" else "KSeF"

            # Weryfikacja sankcyjna z cache (jeden kontrahent sprawdzany 1 raz)
            status_aml = get_contractor_aml_status(inv.sprzedawca.nip, inv.sprzedawca.nazwa)

            # Pozycje faktury kosztowej
            pozycje_koszt = []
            has_unapproved_ai = False
            has_do_wyjasnienia = False
            inv_ai_sugestia = None
            inv_ai_porada = None

            for p_idx, pw in enumerate(audit.pozycje_wyniki, start=1):
                item_key = f"{inv.numer.strip()}::{pw.opis.strip().lower()}"
                item_key_norm = f"{inv.numer.strip()}::{CostClassifier.normalize_desc(pw.opis)}"
                p_kwal = pw.kwalifikacja.value
                p_label = (
                    "✅ 100% Firmowy"
                    if pw.kwalifikacja == KwalifikacjaKosztu.FIRMOWY_100
                    else "🚗 50% Samochód"
                    if pw.kwalifikacja == KwalifikacjaKosztu.SAMOCHOD_50
                    else "⛔ 0% Prywatny (Wykluczono)"
                    if pw.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0
                    else "⚠️ Wymaga decyzji"
                )
                p_uzasadnienie = pw.uzasadnienie
                p_zrodlo = pw.zrodlo_decyzji
                p_wymaga_zatwierdzenia = pw.kwalifikacja == KwalifikacjaKosztu.DO_WYJASNIENIA
                p_zatwierdzony = pw.zrodlo_decyzji == "DECYZJA_RECZNA"
                p_ai_sugestia = None
                p_ai_porada = None

                # Sprawdź czy pozycja ma sugestię AI
                sug = ai_sugestie.get(item_key) or ai_sugestie.get(item_key_norm)
                if sug:
                    p_ai_sugestia = sug.kwalifikacja_sugerowana
                    p_ai_porada = sug.porada_ksiegowa
                    if not inv_ai_sugestia:
                        inv_ai_sugestia = sug.kwalifikacja_sugerowana
                        inv_ai_porada = sug.porada_ksiegowa

                    if pw.zrodlo_decyzji == "DECYZJA_RECZNA":
                        # Przedsiębiorca podjął decyzję ręczną - ma ona bezwzględne pierwszeństwo przed AI!
                        p_zatwierdzony = True
                        p_wymaga_zatwierdzenia = False
                        p_kwal = pw.kwalifikacja.value
                        p_label = (
                            "✅ 100% Firmowy"
                            if pw.kwalifikacja == KwalifikacjaKosztu.FIRMOWY_100
                            else "🚗 50% Samochód"
                            if pw.kwalifikacja == KwalifikacjaKosztu.SAMOCHOD_50
                            else "⛔ 0% Prywatny (Wykluczono)"
                            if pw.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0
                            else "⚠️ Wymaga decyzji"
                        )
                    elif sug.zatwierdzony:
                        p_zatwierdzony = True
                        p_wymaga_zatwierdzenia = False
                        p_kwal = sug.kwalifikacja_sugerowana
                        p_label = (
                            "✅ 100% Firmowy"
                            if sug.kwalifikacja_sugerowana == "FIRMOWY_100"
                            else "🚗 50% Samochód"
                            if sug.kwalifikacja_sugerowana == "SAMOCHOD_50"
                            else "⛔ 0% Prywatny (Wykluczono)"
                            if sug.kwalifikacja_sugerowana == "PRYWATNY_0"
                            else "⚠️ Wymaga decyzji"
                        )
                    else:
                        has_unapproved_ai = True
                        p_wymaga_zatwierdzenia = True
                        p_kwal = sug.kwalifikacja_sugerowana
                        p_label = (
                            "🤖 100% Firmowy (AI)"
                            if sug.kwalifikacja_sugerowana == "FIRMOWY_100"
                            else "🤖 50% Samochód (AI)"
                            if sug.kwalifikacja_sugerowana == "SAMOCHOD_50"
                            else "🤖 0% Prywatny (AI)"
                        )
                        p_uzasadnienie = sug.porada_ksiegowa
                        p_zrodlo = "AI_SUGESTIA"

                if (
                    (p_kwal == "DO_WYJASNIENIA" or pw.kwalifikacja == KwalifikacjaKosztu.DO_WYJASNIENIA)
                    and pw.zrodlo_decyzji != "DECYZJA_RECZNA"
                    and not p_zatwierdzony
                ):
                    has_do_wyjasnienia = True
                    p_wymaga_zatwierdzenia = True

                if p_kwal == "FIRMOWY_100":
                    p_vat_do_odliczenia = pw.kwota_vat
                    p_netto_do_kup = pw.wartosc_netto
                elif p_kwal == "SAMOCHOD_50":
                    p_vat_do_odliczenia = (pw.kwota_vat * Decimal("0.50")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    p_netto_do_kup = pw.wartosc_netto
                elif p_kwal == "PRYWATNY_0":
                    p_vat_do_odliczenia = Decimal("0.00")
                    p_netto_do_kup = Decimal("0.00")
                else:  # DO_WYJASNIENIA
                    p_vat_do_odliczenia = Decimal("0.00")
                    p_netto_do_kup = Decimal("0.00")

                pozycje_koszt.append(
                    {
                        "lp": p_idx,
                        "opis": pw.opis,
                        "wartosc_netto": pw.wartosc_netto,
                        "stawka_vat": pw.stawka_vat,
                        "kwota_vat": pw.kwota_vat,
                        "wartosc_brutto": pw.wartosc_brutto,
                        "kwalifikacja": p_kwal,
                        "kwalifikacja_label": p_label,
                        "vat_do_odliczenia": p_vat_do_odliczenia,
                        "netto_do_kup": p_netto_do_kup,
                        "uzasadnienie": p_uzasadnienie,
                        "zrodlo_decyzji": p_zrodlo,
                        "ai_sugestia": p_ai_sugestia,
                        "ai_porada": p_ai_porada,
                        "wymaga_zatwierdzenia": p_wymaga_zatwierdzenia,
                        "zatwierdzony": p_zatwierdzony,
                    }
                )

            # Zasadność biznesowa i wykluczenia (na podstawie faktycznych pozycji po uwzględnieniu AI/decyzji)
            liczba_wykluczen = len([p for p in pozycje_koszt if p["kwalifikacja"] == "PRYWATNY_0"])
            if liczba_wykluczen > 0 and liczba_wykluczen < len(pozycje_koszt):
                zasadnosc_opis = f"Wydatek mieszany: wykluczono {liczba_wykluczen} pozycji prywatnych bez prawa odliczenia (np. TV, pakiet osobisty)."
            elif all(p["kwalifikacja"] == "PRYWATNY_0" for p in pozycje_koszt):
                zasadnosc_opis = "Wydatek w całości prywatny (0% VAT/KUP) – wykluczony z ewidencji podatkowej."
            elif any(p["kwalifikacja"] == "SAMOCHOD_50" for p in pozycje_koszt):
                zasadnosc_opis = "Eksploatacja pojazdu w trybie mieszanym (art. 86a ustawy o VAT – 50% odliczenia)."
            elif any(p["kwalifikacja"] == "DO_WYJASNIENIA" for p in pozycje_koszt):
                zasadnosc_opis = "Wymagana weryfikacja celowości gospodarczej z przedsiębiorcą."
            else:
                zasadnosc_opis = "Wydatek w 100% uzasadniony gospodarczo (zgodny z PKD i profilem firmy)."

            inv_wymaga_zatwierdzenia = (
                has_unapproved_ai or has_do_wyjasnienia or any(p.get("wymaga_zatwierdzenia") for p in pozycje_koszt)
            )

            # Obliczenie kwot kwalifikowanych i odrzuconych dla całej faktury na podstawie pozycji
            unikalne_p_kwal = set(p["kwalifikacja"] for p in pozycje_koszt)
            if len(unikalne_p_kwal) == 1:
                jedyna_kwal = next(iter(unikalne_p_kwal))
                if jedyna_kwal == "FIRMOWY_100":
                    inv_kwalifikowane_netto = inv.suma_netto
                    inv_kwalifikowany_vat = inv.suma_vat
                    inv_odrzucone_netto = Decimal("0.00")
                    inv_odrzucony_vat = Decimal("0.00")
                elif jedyna_kwal == "SAMOCHOD_50":
                    inv_kwalifikowane_netto = inv.suma_netto
                    inv_kwalifikowany_vat = (inv.suma_vat * Decimal("0.50")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    inv_odrzucone_netto = Decimal("0.00")
                    inv_odrzucony_vat = Decimal("0.00")
                elif jedyna_kwal == "PRYWATNY_0":
                    inv_kwalifikowane_netto = Decimal("0.00")
                    inv_kwalifikowany_vat = Decimal("0.00")
                    inv_odrzucone_netto = inv.suma_netto
                    inv_odrzucony_vat = inv.suma_vat
                else:
                    inv_kwalifikowane_netto = Decimal("0.00")
                    inv_kwalifikowany_vat = Decimal("0.00")
                    inv_odrzucone_netto = Decimal("0.00")
                    inv_odrzucony_vat = Decimal("0.00")
            else:
                inv_kwalifikowane_netto = sum((p["netto_do_kup"] for p in pozycje_koszt), Decimal("0.00"))
                inv_kwalifikowany_vat = sum((p["vat_do_odliczenia"] for p in pozycje_koszt), Decimal("0.00"))
                inv_odrzucone_netto = sum(
                    (p["wartosc_netto"] for p in pozycje_koszt if p["kwalifikacja"] == "PRYWATNY_0"), Decimal("0.00")
                )
                inv_odrzucony_vat = sum(
                    (p["kwota_vat"] for p in pozycje_koszt if p["kwalifikacja"] == "PRYWATNY_0"), Decimal("0.00")
                )

            # Dla faktury jednopozycyjnej upewnij się, że kwalifikacja ogólna odpowiada jedynej pozycji
            if len(pozycje_koszt) == 1:
                kwal_kod = pozycje_koszt[0]["kwalifikacja"]
                if kwal_kod == "SAMOCHOD_50":
                    kwal_tekst = "🚗 Samochód 50% (art. 86a)"
                    status_tekst = "Zatwierdzona" if pozycje_koszt[0]["zatwierdzony"] else "Do akceptacji"
                elif kwal_kod == "FIRMOWY_100":
                    kwal_tekst = "✅ 100% Firmowy"
                    status_tekst = "Zatwierdzona" if pozycje_koszt[0]["zatwierdzony"] else "Do akceptacji"
                elif kwal_kod == "PRYWATNY_0":
                    kwal_tekst = "⛔ Prywatny (0% VAT/KUP)"
                    status_tekst = "Wykluczona"
                elif kwal_kod == "DO_WYJASNIENIA":
                    kwal_tekst = "⚠️ Wymaga wyjaśnienia"
                    status_tekst = "Wymaga decyzji"
            elif len(pozycje_koszt) > 1:
                kwalifikacje = [p["kwalifikacja"] for p in pozycje_koszt]
                if any(k == "DO_WYJASNIENIA" for k in kwalifikacje):
                    kwal_tekst = "⚠️ Wymaga wyjaśnienia"
                    status_tekst = "Wymaga decyzji"
                    kwal_kod = "DO_WYJASNIENIA"
                elif any(k == "PRYWATNY_0" for k in kwalifikacje) and any(k == "FIRMOWY_100" for k in kwalifikacje):
                    kwal_tekst = "Mieszana (wykluczenia prywatne)"
                    status_tekst = "Do akceptacji"
                    kwal_kod = "MIESZANA"
                elif all(k == "PRYWATNY_0" for k in kwalifikacje):
                    kwal_tekst = "⛔ Prywatny (0% VAT/KUP)"
                    status_tekst = "Wykluczona"
                    kwal_kod = "PRYWATNY_0"
                elif all(k == "SAMOCHOD_50" for k in kwalifikacje):
                    kwal_tekst = "🚗 Samochód 50% (art. 86a)"
                    status_tekst = "Do akceptacji"
                    kwal_kod = "SAMOCHOD_50"
                elif all(k == "FIRMOWY_100" for k in kwalifikacje):
                    kwal_tekst = "✅ 100% Firmowy"
                    status_tekst = "Do akceptacji"
                    kwal_kod = "FIRMOWY_100"
                else:
                    kwal_tekst = "Częściowo odliczalny"
                    status_tekst = "Do akceptacji"
                    kwal_kod = "MIESZANA"

            expense_items.append(
                ExpenseItemReview(
                    lp=idx,
                    data=inv.data_wystawienia,
                    numer=inv.numer,
                    sprzedawca_nazwa=inv.sprzedawca.nazwa,
                    sprzedawca_nip=inv.sprzedawca.nip,
                    glowny_przedmiot=opis_glowny,
                    kwota_netto=inv.suma_netto,
                    kwota_vat=inv.suma_vat,
                    kwota_brutto=inv.suma_brutto,
                    kwalifikacja_podatkowa=kwal_tekst,
                    status_weryfikacji=status_tekst,
                    zrodlo=zrodlo_val,
                    status_aml=status_aml,
                    pozycje=pozycje_koszt,
                    kwalifikowany_vat=inv_kwalifikowany_vat,
                    kwalifikowane_netto=inv_kwalifikowane_netto,
                    odrzucony_vat_prywatny=inv_odrzucony_vat,
                    odrzucone_netto_prywatne=inv_odrzucone_netto,
                    zasadnosc_opis=zasadnosc_opis,
                    ai_sugestia=inv_ai_sugestia,
                    ai_porada=inv_ai_porada,
                    wymaga_zatwierdzenia=inv_wymaga_zatwierdzenia,
                    zatwierdzony=all(p.get("zatwierdzony", False) for p in pozycje_koszt) if pozycje_koszt else False,
                    plik_zrodlowy=inv.plik_zrodlowy,
                    ksef_numer_referencyjny=inv.ksef_numer_referencyjny,
                    kwalifikacja_kod=kwal_kod,
                )
            )
            suma_koszt_netto += inv.suma_netto
            suma_koszt_vat += inv.suma_vat
            suma_koszt_brutto += inv.suma_brutto

            # Wykrycie pozycji do wyjaśnienia lub pozycji prywatnych do zatwierdzenia
            for p in pozycje_koszt:
                kwal = p.get("kwalifikacja")
                wymaga_zatw = p.get("wymaga_zatwierdzenia", False)
                zatwierdzony = p.get("zatwierdzony", False)
                zrodlo = p.get("zrodlo_decyzji", "")

                # Tylko pozycje niejednoznaczne lub unapproved AI suggestions trafiają do do_wyjasnienia
                if (
                    (kwal == "DO_WYJASNIENIA" or wymaga_zatw)
                    and not zatwierdzony
                    and zrodlo not in ("REGULA_KONTRAHENTA", "REGULA_GLOBALNA")
                ):
                    clarification_items.append(
                        ClarificationItemReview(
                            lp=clarification_idx,
                            numer_faktury=inv.numer,
                            kontrahent_nazwa=inv.sprzedawca.nazwa,
                            kontrahent_nip=inv.sprzedawca.nip,
                            pozycja_opis=p["opis"],
                            kwota_netto=p["wartosc_netto"],
                            kwota_vat=p["kwota_vat"],
                            status="DO_WYJASNIENIA",
                            uzasadnienie=p.get("uzasadnienie", "Wymaga decyzji przedsiębiorcy"),
                            pytanie_do_uzytkownika=f"Pozycja '{p['opis']}' ({p['wartosc_netto']:.2f} zł netto) – zatwierdź lub wybierz kwalifikację.",
                            sugerowana_odpowiedz=p.get("ai_porada", "Zatwierdź lub wybierz stawkę"),
                        )
                    )
                    clarification_idx += 1

        # Wykrycie faktur zrelokowanych (Auto-Routing)
        relokacje_list: List[Dict[str, Any]] = []
        for inv in faktury_sprzedaz + faktury_koszt:
            if getattr(inv, "relokacja", None):
                relokacje_list.append(inv.relokacja)

        return cls(
            profil=profile,
            rok=rok_str,
            miesiac=miesiac_str,
            sprzedaz=sales_items,
            koszty=expense_items,
            do_wyjasnienia=clarification_items,
            duplikaty=duplikaty,
            relokacje=relokacje_list,
            laczna_sprzedaz_netto=suma_sprzedaz_netto,
            laczna_sprzedaz_vat=suma_sprzedaz_vat,
            laczna_sprzedaz_brutto=suma_sprzedaz_brutto,
            laczny_koszt_netto=suma_koszt_netto,
            laczny_koszt_vat=suma_koszt_vat,
            laczny_koszt_brutto=suma_koszt_brutto,
            ostrzezenie_sieci_aml=wykryto_blad_sieci_aml,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nip": self.profil.nip,
            "firma": self.profil.nazwa,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "laczna_sprzedaz_netto": str(self.laczna_sprzedaz_netto),
            "laczna_sprzedaz_vat": str(self.laczna_sprzedaz_vat),
            "laczna_sprzedaz_brutto": str(self.laczna_sprzedaz_brutto),
            "laczny_koszt_netto": str(self.laczny_koszt_netto),
            "laczny_koszt_vat": str(self.laczny_koszt_vat),
            "laczny_koszt_brutto": str(self.laczny_koszt_brutto),
            "laczny_kwalifikowany_vat": str(self.laczny_kwalifikowany_vat),
            "laczne_kwalifikowane_netto": str(self.laczne_kwalifikowane_netto),
            "laczny_odrzucony_vat_prywatny": str(self.laczny_odrzucony_vat_prywatny),
            "laczne_odrzucone_netto_prywatne": str(self.laczne_odrzucone_netto_prywatne),
            "sprzedaz": [s.to_dict() for s in self.sprzedaz],
            "koszty": [k.to_dict() for k in self.koszty],
            "do_wyjasnienia": [c.to_dict() for c in self.do_wyjasnienia],
            "duplikaty": [d.to_dict() for d in self.duplikaty],
            "relokacje": self.relokacje,
        }

    def generate_markdown(self) -> str:
        """Generuje czytelny raport markdown ze wszystkimi tabelami weryfikacyjnymi."""
        stawka_proc = int(Decimal(str(self.profil.domyslna_stawka_ryczaltu)) * 100)

        linie = [
            f"# 📋 Przegląd Dokumentów Przed Rozliczeniem – {self.rok}-{self.miesiac}",
            f"**Firma:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Forma opodatkowania:** {self.profil.forma_opodatkowania.value} (Stawka ryczałtu: {stawka_proc}%)",
            "**Status weryfikacji:** ⏳ Oczekiwanie na zapoznanie i akceptację przedsiębiorcy",
            "",
        ]

        if self.ostrzezenie_sieci_aml:
            linie.extend(
                [
                    "> [!WARNING]",
                    "> ### ⚠️ UWAGA: NIEKOMPLETNA WERYFIKACJA AML (BŁĄD SIECI / TRYB OFFLINE)",
                    "> Dla części kontrahentów nie udało się pobrać aktualnego statusu z API Białej Listy MF z powodu braku połączenia internetowego.",
                    "> **Nie zamykaj rozliczenia bez uprzedniej weryfikacji online!**",
                    "> ",
                    "> 👉 **Zalecenie:** Upewnij się, że masz połączenie z Internetem i uruchom ponowną weryfikację:",
                    f"> `python -m src.cli weryfikuj-miesiac --nip {self.profil.nip} --rok {self.rok} --miesiac {self.miesiac} --force`",
                    "",
                ]
            )

        # Sekcja relokacji dokumentów Non-KSeF (jeśli wystąpiły)
        if self.relokacje:
            linie.extend(
                [
                    "---",
                    "## 🔄 Informacja o Automatycznej Relokacji Dokumentów Non-KSeF",
                    "Wykryto dokumenty umieszczone w niewłaściwym folderze. Zostały one automatycznie przeniesione do właściwego katalogu,",
                    "a w pierwotnym katalogu utworzono plik-znacznik `.PRZENIESIONO.txt` ze szczegółami operacji:",
                    "",
                    "| Lp. | Dokument | Relokacja | Powód kwalifikacji |",
                    "| :---: | :--- | :--- | :--- |",
                ]
            )
            for idx, r in enumerate(self.relokacje, start=1):
                linie.append(
                    f"| {idx} | `{r.get('oryginalny_plik')}` | `{r.get('pierwotny_typ')}` ➔ **`{r.get('faktyczny_typ')}`** | {r.get('powod')} |"
                )
            linie.append("")

        # Sekcja 0: Wykryte duplikaty dokumentów (jeśli występują)
        if self.duplikaty:
            linie.extend(
                [
                    "---",
                    "## 🚨 0. Wykryte Duplikaty Dokumentów (Ochrona przed podwójnym księgowaniem)",
                    "System wykrył zdublowane dokumenty i zneutralizował ryzyko podwójnego ujęcia kosztów lub podatku VAT:",
                    "",
                    "| Lp. | Wykryty dokument / plik | Kontrahent | Brutto | Typ kolizji | Wyjaśnienie i Ochrona Podatkowa |",
                    "| :---: | :--- | :--- | :---: | :---: | :--- |",
                ]
            )
            for idx, d in enumerate(self.duplikaty, start=1):
                typ_label = {
                    DuplicateType.KSEF_COLLISION: "🏛️ KSeF First (kolizja z KSeF)",
                    DuplicateType.CROSS_MONTH_DUPLICATE: f"📅 Duplikat z m-ca {d.rok_pierwotny}-{d.miesiac_pierwotny}",
                    DuplicateType.SAME_PERIOD_DUPLICATE: "📄 Zdublowany plik w tym m-cu",
                }.get(d.typ_duplikatu, d.typ_duplikatu.value)

                kontrahent_info = (
                    f"{d.faktura_odrzucona.sprzedawca.nazwa} (`{d.faktura_odrzucona.sprzedawca.nip}`)"
                    if d.faktura_odrzucona.typ == InvoiceType.KOSZT
                    else f"{d.faktura_odrzucona.nabywca.nazwa} (`{d.faktura_odrzucona.nabywca.nip}`)"
                )
                plik_odrz = (
                    f"`{d.plik_zrodlowy_odrzucony}`" if d.plik_zrodlowy_odrzucony else f"`{d.faktura_odrzucona.numer}`"
                )
                wyjasnienie = f"**{d.opis_problemu}**<br>*{d.rekomendacja}*"
                linie.append(
                    f"| {idx} | {plik_odrz} (nr: `{d.faktura_odrzucona.numer}`) | {kontrahent_info} | {d.faktura_odrzucona.suma_brutto:.2f} zł | {typ_label} | {wyjasnienie} |"
                )

            linie.extend(
                [
                    "",
                    "> 🛡️ **Zastosowane Zabezpieczenie:**",
                    "> Wszystkie powyższe zdublowane pozycje zostały **wykluczone z bieżącego księgowania**.",
                    "> Faktury są ujęte wyłącznie jeden raz (właściwe źródło KSeF lub miesiąc pierwotny), co gwarantuje pełną zgodność prawną z art. 86 i 112b ustawy o VAT.",
                    "",
                ]
            )

        linie.extend(
            [
                "---",
                "## 📈 1. Faktury Sprzedaży (Przychody) – Do Zaznajomienia i Weryfikacji Kompletności",
                "Poniższe faktury sprzedaży zostały pobrane z KSeF oraz wyekstrahowane z archiwum non-ksef i zakwalifikowane do przychodów w bieżącym miesiącu:",
                "",
                "| Lp. | Źródło | Data | Numer faktury | Nabywca | NIP | Przedmiot sprzedaży | Netto | Ryczałt | VAT | Brutto | Status AML |",
                "| :---: | :---: | :---: | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |",
            ]
        )

        if not self.sprzedaz:
            linie.append(
                "| - | - | - | *Brak faktur sprzedaży w tym miesiącu* | - | - | - | 0.00 zł | - | 0.00 zł | 0.00 zł | - |"
            )
        else:
            for s in self.sprzedaz:
                zrodlo_badge = "📁 Non-KSeF" if s.zrodlo == "Non-KSeF" else "🏛️ KSeF"
                ryczalt_kwota = (s.kwota_netto * s.stawka_ryczaltu).quantize(Decimal("0.01"))
                s_proc_val = f"{s.stawka_ryczaltu * 100:.2f}".rstrip("0").rstrip(".") + "%"
                linie.append(
                    f"| {s.lp} | {zrodlo_badge} | {s.data} | `{s.numer}` | {s.nabywca_nazwa} | `{s.nabywca_nip}` | {s.przedmiot} | {s.kwota_netto:.2f} zł | {s_proc_val} ({ryczalt_kwota:.2f} zł) | {s.kwota_vat:.2f} zł | {s.kwota_brutto:.2f} zł | {s.status_aml} |"
                )
            linie.append(
                f"| | | | | **SUMA PRZYCHODÓW** | | | **{self.laczna_sprzedaz_netto:.2f} zł** | | **{self.laczna_sprzedaz_vat:.2f} zł** | **{self.laczna_sprzedaz_brutto:.2f} zł** | |"
            )

        linie.extend(
            [
                "",
                "> ℹ️ **Weryfikacja kompletności przychodów:**",
                f"> Sprawdź, czy powyższa lista zawiera wszystkie faktury sprzedaży wystawione za okres **{self.rok}-{self.miesiac}**.",
                "> *Czy brakuje jakiejś faktury (np. wystawionej poza KSeF, korygującej lub czekającej na wystawienie)?*",
                "",
                "---",
                "## 🧾 2. Faktury Kosztowe (Zakupy) – Do Weryfikacji i Akceptacji Przedsiębiorcy",
                "Poniższe faktury kosztowe zostały pobrane z KSeF oraz wyekstrahowane z archiwum non-ksef na NIP Twojej działalności:",
                "",
                "| Lp. | Źródło | Data | Numer faktury | Sprzedawca | NIP | Przedmiot zakupu | Netto | VAT | Brutto | Kwalifikacja podatkowa | Status AML |",
                "| :---: | :---: | :---: | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :--- | :---: |",
            ]
        )

        if not self.koszty:
            linie.append(
                "| - | - | - | *Brak faktur kosztowych w tym miesiącu* | - | - | - | 0.00 zł | 0.00 zł | 0.00 zł | - | - |"
            )
        else:
            for k in self.koszty:
                zrodlo_badge = "📁 Non-KSeF" if k.zrodlo == "Non-KSeF" else "🏛️ KSeF"
                linie.append(
                    f"| {k.lp} | {zrodlo_badge} | {k.data} | `{k.numer}` | {k.sprzedawca_nazwa} | `{k.sprzedawca_nip}` | {k.glowny_przedmiot} | {k.kwota_netto:.2f} zł | {k.kwota_vat:.2f} zł | {k.kwota_brutto:.2f} zł | {k.kwalifikacja_podatkowa} | {k.status_aml} |"
                )
            linie.append(
                f"| | | | | **SUMA WYDATKÓW** | | | **{self.laczny_koszt_netto:.2f} zł** | **{self.laczny_koszt_vat:.2f} zł** | **{self.laczny_koszt_brutto:.2f} zł** | | |"
            )

        linie.extend(
            [
                "",
                "> ⚠️ **Weryfikacja przynależności faktur:**",
                "> Sprawdź powyższą listę i potwierdź: *Czy wszystkie te faktury faktycznie należą do Ciebie i dotyczą Twojej działalności gospodarczej?*",
                "> *Czy któraś faktura została wystawiona na Twój NIP pomyłkowo lub nie dotyczy Twojej firmy?*",
                "",
                "---",
                "## 🔍 3. Pozycje i Faktury Wymagające Wyjaśnienia (Human-in-the-Loop)",
            ]
        )

        if not self.do_wyjasnienia:
            linie.extend(
                [
                    "✅ **Wszystkie pozycje kosztowe zostały sklasyfikowane automatycznie bez wątpliwości.**",
                    "Brak pozycji o niejasnym statusie lub wymagających dodatkowej decyzji.",
                ]
            )
        else:
            linie.extend(
                [
                    "Wykryto pozycje niejednoznaczne lub wykluczone jako wydatki prywatne/osobiste. Przed finalnym rozliczeniem potwierdź decyzje:",
                    "",
                    "| Lp. | Faktura | Sprzedawca | Pozycja w fakturze | Netto | VAT | Status | Pytanie do Ciebie / Sugestia |",
                    "| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |",
                ]
            )
            for c in self.do_wyjasnienia:
                status_icon = "⚠️ DO WYJAŚNIENIA" if c.status == "DO_WYJASNIENIA" else "⛔ PRYWATNY (0% VAT)"
                linie.append(
                    f"| {c.lp} | `{c.numer_faktury}` | {c.kontrahent_nazwa} | **{c.pozycja_opis}** | {c.kwota_netto:.2f} zł | {c.kwota_vat:.2f} zł | `{status_icon}` | {c.pytanie_do_uzytkownika} |"
                )

            linie.extend(
                [
                    "",
                    "### 💬 Jak odpowiedzieć asystentowi:",
                    "Wystarczy, że napiszesz w czacie np.:",
                    '* *"Wszystkie faktury kosztowe są moje. W Play usługi inne to stałe IP serwera (firmowe 100%), a pakiet medyczny to prywatny (potwierdzam wykluczenie)."*',
                    '* *"W fakturach sprzedaży wszystko się zgadza, niczego nie brakuje – możemy przejść do rozliczenia."*',
                    "",
                    "Asystent automatycznie zapisze nowe reguły w pliku `reguly_kosztowe.json` i przejdzie do deterministycznego wyliczenia podatków.",
                ]
            )

        return "\n".join(linie)
