"""
Główna usługa rozliczeniowa (Poziom 3).
Spina ewidencję księgową (Poziom 2), kalkulatory ZUS, PIT-28 i VAT
oraz generuje kompletną Paczkę Przelewów Podatnika i raporty archiwalne.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.core.company import CompanyProfile, FormaOpodatkowania
from src.core.io import atomic_write_json, atomic_write_text
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_2_bookkeeping.ledger import BookkeepingService, MonthlyLedger
from src.skills.ryczalt_tools import PIT28CalculationResult, calculate_pit28_advance
from src.skills.vat_tools import VATBalanceResult, calculate_vat_settlement
from src.skills.zus_tools import ZUSCalculationResult, calculate_zus

from .reports import (
    AuditMarkdownReporter,
    LedgerMarkdownReporter,
    SettlementMarkdownReporter,
    format_rate_pct,
)

_format_rate_pct = format_rate_pct


@dataclass
class PaymentItem:
    """Pojedynczy przelew podatkowo-składkowy do wykonania przez przedsiębiorcę."""

    nazwa: str  # np. "ZUS", "Urząd Skarbowy - PIT-28", "Urząd Skarbowy - VAT-7"
    kwota: Decimal  # Kwota do przelania
    termin_platnosci: str  # YYYY-MM-DD
    rachunek_docelowy: str  # Informacja o rachunku (np. NRS ZUS, Mikrorachunek podatkowy)
    tytul_przelewu: str  # Tytuł transakcji


@dataclass
class MonthlySettlementResult:
    """Kompletny wynik rozliczenia miesiąca."""

    profil: CompanyProfile
    rok: str
    miesiac: str
    ledger: MonthlyLedger
    zus: ZUSCalculationResult
    pit28: Optional[PIT28CalculationResult]
    vat: Optional[VATBalanceResult]
    przychod_roczny_narastajaco: Decimal
    paczka_przelewow: List[PaymentItem] = field(default_factory=list)

    @property
    def suma_wszystkich_zobowiazan(self) -> Decimal:
        """Łączna kwota przelewów do wykonania w danym miesiącu."""
        return sum((p.kwota for p in self.paczka_przelewow), Decimal("0.00"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nip": self.profil.nip,
            "firma": self.profil.nazwa,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "przychod_roczny_narastajaco": str(self.przychod_roczny_narastajaco),
            "suma_zobowiazan_lacznie": str(self.suma_wszystkich_zobowiazan),
            "przelewy": [
                {
                    "nazwa": p.nazwa,
                    "kwota": str(p.kwota),
                    "termin": p.termin_platnosci,
                    "rachunek": p.rachunek_docelowy,
                    "tytul": p.tytul_przelewu,
                }
                for p in self.paczka_przelewow
            ],
            "zus": self.zus.to_dict(),
            "pit28": self.pit28.to_dict() if self.pit28 else None,
            "vat": self.vat.to_dict() if self.vat else None,
            "ewidencja": self.ledger.to_dict(),
        }

    def generate_markdown_report(self) -> str:
        """Generuje czytelny raport podsumowujący w formacie Markdown."""
        return SettlementMarkdownReporter.generate(self)

    def generate_ewidencja_przychodow_report(self) -> str:
        """Generuje dokument ewidencja-przychodow.md."""
        return LedgerMarkdownReporter.generate_monthly(self)

    def generate_ewidencja_przychodow_sumy_report(self) -> str:
        """Generuje dokument ewidencja-przychodow-sumy.md."""
        return LedgerMarkdownReporter.generate_ytd(self)

    def generate_sprawozdanie_report(self) -> str:
        """Generuje dokument sprawozdanie.md (audyt podatkowy)."""
        return AuditMarkdownReporter.generate(self)


class SettlementService:
    """
    Główny silnik realizujący pełne rozliczenie miesiąca.
    """

    @classmethod
    def calculate_ytd_revenue(cls, profile: CompanyProfile, rok: str, up_to_month: str) -> Decimal:
        """
        Oblicza sumę przychodów od początku danego roku do wskazanego miesiąca włącznie.
        """
        target_m = int(up_to_month)
        rok_str = str(rok)
        suma_ytd = Decimal("0.00")

        for m in range(1, target_m + 1):
            m_str = f"{m:02d}"
            faktury = InvoiceStorage.list_sales_invoices_for_pit(profile=profile, rok=rok_str, miesiac=m_str)
            for inv in faktury:
                suma_ytd += inv.suma_netto

        return suma_ytd

    @classmethod
    def settle_month(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        nadwyzka_vat_poprzedni: Decimal = Decimal("0.00"),
        zapisz_raporty: bool = True,
    ) -> MonthlySettlementResult:
        """
        Przeprowadza pełne rozliczenie wybranego miesiąca.
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        # 1. Poziom 2: Księgowanie faktur
        ledger = BookkeepingService.process_month(profile=profile, rok=rok_str, miesiac=miesiac_str)

        # 2. Wyznaczenie przychodu narastająco do progów zdrowotnej
        przychod_ytd = cls.calculate_ytd_revenue(profile=profile, rok=rok_str, up_to_month=miesiac_str)

        # 3. Poziom 3: Obliczenie ZUS należnego za bieżący miesiąc
        uproszczona_prog = (
            profile.zus.prog_zdrowotnej_uproszczony
            if getattr(profile.zus, "metoda_zdrowotna", "UPROSZCZONA_UBIEGLY_ROK") == "UPROSZCZONA_UBIEGLY_ROK"
            else None
        )

        current_zus_typ = (
            profile.zus.get_typ_for_period(rok_str, miesiac_str)
            if hasattr(profile.zus, "get_typ_for_period")
            else profile.zus.typ
        )

        zus_result = calculate_zus(
            rok=rok_str,
            miesiac=miesiac_str,
            typ_zus=current_zus_typ,
            chorobowe_dobrowolne=profile.zus.chorobowe_dobrowolne,
            forma_opodatkowania=profile.forma_opodatkowania,
            przychod_roczny_narastajaco=przychod_ytd,
            uproszczona_zdrowotna_prog=uproszczona_prog,
        )

        # 4. Poziom 3: Wyznaczenie składek ZUS do odliczenia w PIT
        # Zgodnie z art. 11 ust. 1 ustawy o ryczałcie oraz art. 26 ust. 1 pkt 2 lit. a ustawy o PIT:
        # a) Odlicza się składki ZAPŁACONE w danym miesiącu (zasada kasowa: w miesiącu M płaci się ZUS za M-1)
        # b) Odlicza się wyłącznie ubezpieczenia społeczne (emerytalna, rentowa, chorobowa, wypadkowa) - BEZ Funduszu Pracy!
        # c) Odlicza się 50% zapłaconej składki zdrowotnej
        zasada_odliczen = getattr(profile.zus, "zasada_odliczen", "KASOWA")

        if zasada_odliczen == "KASOWA":
            m_int = int(miesiac_str)
            if m_int > 1:
                prev_m_str = f"{m_int - 1:02d}"
                prev_rok_str = rok_str
            else:
                prev_m_str = "12"
                prev_rok_str = str(int(rok_str) - 1)

            prev_rozliczenie_file = (
                profile.katalog_firmy / "rozliczenia" / prev_rok_str / prev_m_str / "rozliczenie.json"
            )
            if prev_rozliczenie_file.exists():
                try:
                    with open(prev_rozliczenie_file, "r", encoding="utf-8") as f:
                        prev_data = json.load(f)
                    prev_zus = prev_data.get("zus", {})
                    skladki_spol_dict = prev_zus.get("skladki_spoleczne", {})
                    if "odliczalne" in skladki_spol_dict:
                        skladki_spoleczne_do_odliczenia = Decimal(str(skladki_spol_dict["odliczalne"]))
                    else:
                        suma_spol = Decimal(str(skladki_spol_dict.get("suma", "0.00")))
                        fp = Decimal(str(skladki_spol_dict.get("fundusz_pracy", "0.00")))
                        skladki_spoleczne_do_odliczenia = max(Decimal("0.00"), suma_spol - fp)
                    skladka_zdrowotna_zaplacona = Decimal(
                        str(prev_zus.get("skladka_zdrowotna", {}).get("kwota", "0.00"))
                    )
                except Exception:
                    skladki_spoleczne_do_odliczenia = zus_result.spoleczne_odliczalne
                    skladka_zdrowotna_zaplacona = zus_result.zdrowotna
            else:
                prev_ytd = cls.calculate_ytd_revenue(profile=profile, rok=prev_rok_str, up_to_month=prev_m_str)
                prev_zus_typ = (
                    profile.zus.get_typ_for_period(prev_rok_str, prev_m_str)
                    if hasattr(profile.zus, "get_typ_for_period")
                    else profile.zus.typ
                )
                prev_zus_calc = calculate_zus(
                    rok=prev_rok_str,
                    miesiac=prev_m_str,
                    typ_zus=prev_zus_typ,
                    chorobowe_dobrowolne=profile.zus.chorobowe_dobrowolne,
                    forma_opodatkowania=profile.forma_opodatkowania,
                    przychod_roczny_narastajaco=prev_ytd,
                    uproszczona_zdrowotna_prog=uproszczona_prog,
                )
                skladki_spoleczne_do_odliczenia = prev_zus_calc.spoleczne_odliczalne
                skladka_zdrowotna_zaplacona = prev_zus_calc.zdrowotna
        else:
            skladki_spoleczne_do_odliczenia = zus_result.spoleczne_odliczalne
            skladka_zdrowotna_zaplacona = zus_result.zdrowotna

        # 5. Poziom 3: Obliczenie PIT-28 (jeśli Ryczałt)
        pit28_result: Optional[PIT28CalculationResult] = None
        if profile.forma_opodatkowania == FormaOpodatkowania.RYCZALT:
            pit28_result = calculate_pit28_advance(
                rok=rok_str,
                miesiac=miesiac_str,
                sumy_przychodow_wg_stawek=ledger.ewidencja_przychodow.sumy_wg_stawek,
                skladki_spoleczne_do_odliczenia=skladki_spoleczne_do_odliczenia,
                skladka_zdrowotna_zaplacona=skladka_zdrowotna_zaplacona,
            )

        # 5. Poziom 3: Obliczenie VAT (jeśli płatnik VAT)
        vat_result: Optional[VATBalanceResult] = None
        if profile.platnik_vat:
            vat_result = calculate_vat_settlement(
                rejestr=ledger.rejestr_vat,
                nadwyzka_z_poprzedniego_miesiaca=nadwyzka_vat_poprzedni,
            )

        # 6. Przygotowanie Paczki Przelewów
        paczka: List[PaymentItem] = []

        # Przelew ZUS
        if zus_result.lacznie_do_zaplaty > Decimal("0.00"):
            paczka.append(
                PaymentItem(
                    nazwa="ZUS (Społeczne + Zdrowotna)",
                    kwota=zus_result.lacznie_do_zaplaty,
                    termin_platnosci=zus_result.termin_platnosci,
                    rachunek_docelowy="Indywidualny Rachunek Składkowy ZUS (NRS)",
                    tytul_przelewu=f"Składki ZUS za {miesiac_str}/{rok_str}",
                )
            )

        # Przelew PIT-28
        if pit28_result and pit28_result.zaliczka_pit28_zaokraglona > 0:
            paczka.append(
                PaymentItem(
                    nazwa="Urząd Skarbowy – Ryczałt PIT-28",
                    kwota=Decimal(str(pit28_result.zaliczka_pit28_zaokraglona)),
                    termin_platnosci=pit28_result.termin_platnosci,
                    rachunek_docelowy="Indywidualny Mikrorachunek Podatkowy",
                    tytul_przelewu=f"Zaliczka PIT-28 za {miesiac_str}/{rok_str}",
                )
            )

        # Przelew VAT-7
        if vat_result and vat_result.vat_do_zaplaty_zaokraglony > 0:
            paczka.append(
                PaymentItem(
                    nazwa="Urząd Skarbowy – Podatek VAT-7",
                    kwota=Decimal(str(vat_result.vat_do_zaplaty_zaokraglony)),
                    termin_platnosci=vat_result.termin_platnosci,
                    rachunek_docelowy="Indywidualny Mikrorachunek Podatkowy",
                    tytul_przelewu=f"Podatek VAT-7 za {miesiac_str}/{rok_str}",
                )
            )

        wynik = MonthlySettlementResult(
            profil=profile,
            rok=rok_str,
            miesiac=miesiac_str,
            ledger=ledger,
            zus=zus_result,
            pit28=pit28_result,
            vat=vat_result,
            przychod_roczny_narastajaco=przychod_ytd,
            paczka_przelewow=paczka,
        )

        # 7. Zapis raportów na dysku
        if zapisz_raporty:
            target_dir = profile.katalog_firmy / "rozliczenia" / rok_str / miesiac_str
            target_dir.mkdir(parents=True, exist_ok=True)

            # Raport maszynowy JSON
            json_path = target_dir / "rozliczenie.json"
            atomic_write_json(json_path, wynik.to_dict(), indent=2, ensure_ascii=False)

            # Główny raport rozliczenia i paczka przelewów
            md_path = target_dir / "rozliczenie.md"
            atomic_write_text(md_path, wynik.generate_markdown_report())

            # 1. Ewidencja przychodów za dany miesiąc
            ep_path = target_dir / "ewidencja-przychodow.md"
            atomic_write_text(ep_path, wynik.generate_ewidencja_przychodow_report())

            # 2. Ewidencja przychodów - sumy roczne (YTD)
            eps_path = target_dir / "ewidencja-przychodow-sumy.md"
            atomic_write_text(eps_path, wynik.generate_ewidencja_przychodow_sumy_report())

            # 3. Sprawozdanie z audytu i czynności księgowych
            spr_path = target_dir / "sprawozdanie.md"
            atomic_write_text(spr_path, wynik.generate_sprawozdanie_report())

            # 4. Automatyczna weryfikacja compliance kontrahentów (AML / Sankcje / Biała Lista)
            try:
                from src.skills.aml_tools import VerificationService

                VerificationService.verify_month(profile, rok_str, miesiac_str, zapisz_pliki=True)
            except Exception:
                pass

        return wynik
