"""
Główna usługa rozliczeniowa (Poziom 3).
Spina ewidencję księgową (Poziom 2), kalkulatory ZUS, PIT-28 i VAT
oraz generuje kompletną Paczkę Przelewów Podatnika i raporty archiwalne.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Dict, Any, List, Optional
import json

from src.core.company import CompanyProfile, FormaOpodatkowania
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_2_bookkeeping.ledger import BookkeepingService, MonthlyLedger
from src.skills.zus_tools import calculate_zus, ZUSCalculationResult
from src.skills.ryczalt_tools import calculate_pit28_advance, PIT28CalculationResult
from src.skills.vat_tools import calculate_vat_settlement, VATBalanceResult


@dataclass
class PaymentItem:
    """Pojedynczy przelew podatkowo-składkowy do wykonania przez przedsiębiorcę."""
    nazwa: str               # np. "ZUS", "Urząd Skarbowy - PIT-28", "Urząd Skarbowy - VAT-7"
    kwota: Decimal           # Kwota do przelania
    termin_platnosci: str    # YYYY-MM-DD
    rachunek_docelowy: str   # Informacja o rachunku (np. NRS ZUS, Mikrorachunek podatkowy)
    tytul_przelewu: str      # Tytuł transakcji


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
        linie = [
            f"# Raport Rozliczenia Miesięcznego – {self.rok}-{self.miesiac}",
            f"**Firma:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Forma opodatkowania:** {self.profil.forma_opodatkowania.value} | **ZUS:** {self.profil.zus.typ.value}",
            "",
            "---",
            "## 1. Paczka Przelewów Podatkowych (Do wykonania)",
            "",
            "| Odbiorca / Zobowiązanie | Kwota do zapłaty | Termin płatności | Rachunek docelowy | Tytuł przelewu |",
            "| :--- | :---: | :---: | :--- | :--- |",
        ]

        for p in self.paczka_przelewow:
            linie.append(
                f"| **{p.nazwa}** | **{p.kwota:.2f} zł** | `{p.termin_platnosci}` | {p.rachunek_docelowy} | `{p.tytul_przelewu}` |"
            )

        linie.extend([
            "",
            f"**Łączna suma obciążeń za ten miesiąc:** **{self.suma_wszystkich_zobowiazan:.2f} zł**",
            "",
            "---",
            "## 2. Zestawienie Ewidencji Gospodarczej",
            f"* **Przychód netto w miesiącu:** {self.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł",
            f"* **Przychód roczny narastająco:** {self.przychod_roczny_narastajaco:.2f} zł (próg zdrowotnej: `{self.zus.prog_przychodow_zdrowotna}`)",
            f"* **Liczba faktur sprzedaży:** {len(self.ledger.ewidencja_przychodow.wpisy)}",
            f"* **Liczba faktur kosztowych:** {len(self.ledger.rejestr_vat.wpisy_zakupow)}",
            "",
            "---",
            "## 3. Szczegóły Wyliczeń",
            "",
            "### A. Składki ZUS",
            f"* **Podstawa składek społecznych:** {self.zus.podstawa_spoleczne:.2f} zł",
            f"* **Składki społeczne (emerytalna, rentowa, chorobowa, wypadkowa, FP):** {self.zus.suma_spoleczne:.2f} zł",
            f"* **Podstawa składki zdrowotnej:** {self.zus.podstawa_zdrowotna:.2f} zł",
            f"* **Składka zdrowotna:** {self.zus.zdrowotna:.2f} zł (odliczenie na ryczałcie 50%: {self.zus.odliczenie_zdrowotna_ryczalt_50:.2f} zł)",
            f"* **Razem przelew do ZUS:** **{self.zus.lacznie_do_zaplaty:.2f} zł**",
            "",
        ])

        if self.pit28:
            linie.extend([
                "### B. Ryczałt od Przychodów Ewidencjonowanych (PIT-28)",
                f"* **Przychód do opodatkowania:** {self.pit28.przychod_laczny:.2f} zł",
                f"* **Odliczenie składek społecznych:** -{self.pit28.odliczenie_spoleczne:.2f} zł",
                f"* **Odliczenie 50% składki zdrowotnej:** -{self.pit28.odliczenie_zdrowotna_50:.2f} zł",
                f"* **Podstawa opodatkowania:** {self.pit28.podstawa_opodatkowania:.2f} zł",
                f"* **Podatek wyliczony dokładnie:** {self.pit28.podatek_nalezy_dokladny:.2f} zł",
                f"* **Zaliczka PIT-28 do zapłaty (zaokrąglona):** **{self.pit28.zaliczka_pit28_zaokraglona} zł**",
                "",
            ])

        if self.vat:
            linie.extend([
                "### C. Rozliczenie Podatku VAT (JPK_V7)",
                f"* **VAT należny (ze sprzedaży):** {self.vat.vat_nalezy:.2f} zł",
                f"* **VAT naliczony (z kosztów podlegających odliczeniu):** {self.vat.vat_naliczony:.2f} zł",
                f"* **Różnica VAT:** {self.vat.roznica_vat:.2f} zł",
            ])
            if self.vat.vat_do_zaplaty_zaokraglony > 0:
                linie.append(f"* **Podatek VAT do wpłaty do US:** **{self.vat.vat_do_zaplaty_zaokraglony} zł**")
            else:
                linie.append(f"* **Nadwyżka VAT do przeniesienia na kolejny miesiąc:** **{self.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł**")
            linie.append("")

        # 4. Wyłączenia wydatków osobistych
        odrzucone_pozycje = []
        for audyt in self.ledger.audyt_kosztow:
            for p in audyt.pozycje_wyniki:
                if p.kwalifikacja.value == "PRYWATNY_0":
                    odrzucone_pozycje.append((audyt.numer_faktury, audyt.sprzedawca_nazwa, p))

        if odrzucone_pozycje:
            linie.extend([
                "---",
                "## 4. Wyłączenia Wydatków Osobistych (Ochrona Podatkowa)",
                "Poniższe pozycje zostały wykluczone z kosztów i rejestru VAT jako wydatki prywatne/osobiste:",
                "",
                "| Faktura | Kontrahent | Wykluczona pozycja | Kwota netto | VAT (nieodliczony) | Uzasadnienie |",
                "| :--- | :--- | :--- | :---: | :---: | :--- |",
            ])
            for nr, kontrahent, p in odrzucone_pozycje:
                linie.append(
                    f"| `{nr}` | {kontrahent} | **{p.opis}** | {p.wartosc_netto:.2f} zł | {p.kwota_vat:.2f} zł | {p.uzasadnienie} |"
                )
            linie.extend([
                "",
                f"*Łącznie wykluczono z VAT:* **{self.ledger.laczny_odrzucony_vat_prywatny:.2f} zł** (kwota ta nie powiększyła VAT-u naliczonego).",
                "",
            ])

        # 5. Pytania do przedsiębiorcy
        if self.ledger.pytania_do_uzytkownika:
            linie.extend([
                "---",
                "## ⚠️ Pozycje Wymagające Wyjaśnienia (Human-in-the-Loop)",
                "Przed ostatecznym zamknięciem deklaracji potwierdź kwalifikację poniższych pozycji:",
                "",
            ])
            for q in self.ledger.pytania_do_uzytkownika:
                linie.append(f"* {q}")
            linie.append("")

        return "\n".join(linie)


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
            faktury = InvoiceStorage.list_invoices(
                profile=profile, rok=rok_str, miesiac=m_str, typ=InvoiceType.SPRZEDAZ
            )
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

        # 3. Poziom 3: Obliczenie ZUS
        zus_result = calculate_zus(
            rok=rok_str,
            miesiac=miesiac_str,
            typ_zus=profile.zus.typ,
            chorobowe_dobrowolne=profile.zus.chorobowe_dobrowolne,
            forma_opodatkowania=profile.forma_opodatkowania,
            przychod_roczny_narastajaco=przychod_ytd,
        )

        # 4. Poziom 3: Obliczenie PIT-28 (jeśli Ryczałt)
        pit28_result: Optional[PIT28CalculationResult] = None
        if profile.forma_opodatkowania == FormaOpodatkowania.RYCZALT:
            pit28_result = calculate_pit28_advance(
                rok=rok_str,
                miesiac=miesiac_str,
                sumy_przychodow_wg_stawek=ledger.ewidencja_przychodow.sumy_wg_stawek,
                skladki_spoleczne_do_odliczenia=zus_result.suma_spoleczne,
                skladka_zdrowotna_zaplacona=zus_result.zdrowotna,
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

            json_path = target_dir / "rozliczenie.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(wynik.to_dict(), f, indent=2, ensure_ascii=False)

            md_path = target_dir / "rozliczenie.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(wynik.generate_markdown_report())

        return wynik

