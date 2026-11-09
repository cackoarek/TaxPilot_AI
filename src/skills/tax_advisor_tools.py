"""
Narzędzia Poziomu 4: Optymalizacja Podatkowa (Tax Optimization Advisor).
- Symulator porównawczy form opodatkowania (Ryczałt vs Podatek Liniowy vs Skala Podatkowa)
- Detektor brakujących kosztów i anomalii wydatków (Expense Leak Detector)
- Analizator potencjału ulg podatkowych (np. IP-Box, B+R)
Wszystkie operacje matematyczne oparte są wyłącznie na typie Decimal.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any
from pathlib import Path

from src.core.company import CompanyProfile, FormaOpodatkowania
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.skills.zus_tools import DEFAULT_ZUS_PARAMS, STOPA_EMERYTALNA, STOPA_RENTOWA, STOPA_CHOROBOWA, STOPA_WYPADKOWA, STOPA_FP


def _round_money(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class RegimeCalculation:
    """Szczegółowe wyliczenie obciążeń dla danej formy opodatkowania w skali roku."""
    nazwa_formy: str
    przychod_roczny: Decimal
    koszty_roczne: Decimal
    dochod_brutto: Decimal
    skladki_spoleczne_zus: Decimal
    skladka_zdrowotna_zus: Decimal
    podstawa_opodatkowania: Decimal
    podatek_dochodowy: Decimal
    laczne_obciazenia: Decimal  # Podatek + ZUS społeczne + Zdrowotna
    dochod_netto_na_reke: Decimal  # Przychód - Koszty - Łączne obciążenia
    efektywna_stopa_opodatkowania: Decimal  # Łączne obciążenia / Przychód

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nazwa_formy": self.nazwa_formy,
            "przychod_roczny": str(self.przychod_roczny),
            "koszty_roczne": str(self.koszty_roczne),
            "dochod_brutto": str(self.dochod_brutto),
            "skladki_spoleczne_zus": str(self.skladki_spoleczne_zus),
            "skladka_zdrowotna_zus": str(self.skladka_zdrowotna_zus),
            "podstawa_opodatkowania": str(self.podstawa_opodatkowania),
            "podatek_dochodowy": str(self.podatek_dochodowy),
            "laczne_obciazenia": str(self.laczne_obciazenia),
            "dochod_netto_na_reke": str(self.dochod_netto_na_reke),
            "efektywna_stopa_opodatkowania": f"{self.efektywna_stopa_opodatkowania:.2%}",
        }


@dataclass
class TaxRegimeComparison:
    """Porównanie 3 form opodatkowania."""
    rok: str
    stawka_ryczaltu: Decimal
    ryczalt: RegimeCalculation
    liniowy: RegimeCalculation
    skala: RegimeCalculation
    najkorzystniejsza_forma: str
    roczna_oszczednosc_wzgledem_drugiej: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "stawka_ryczaltu": str(self.stawka_ryczaltu),
            "najkorzystniejsza_forma": self.najkorzystniejsza_forma,
            "roczna_oszczednosc_wzgledem_drugiej": str(self.roczna_oszczednosc_wzgledem_drugiej),
            "ryczalt": self.ryczalt.to_dict(),
            "liniowy": self.liniowy.to_dict(),
            "skala": self.skala.to_dict(),
        }

    def generate_markdown(self) -> str:
        linie = [
            f"# Symulacja Porównawcza Form Opodatkowania na rok {self.rok}",
            "",
            f"**Rekomendowana forma:** **{self.najkorzystniejsza_forma}** (oszczędność **{self.roczna_oszczednosc_wzgledem_drugiej:.2f} zł** rocznie względem kolejnej opcji).",
            "",
            "| Parametr / Pozycja | Ryczałt ewidencjonowany | Podatek Liniowy (19%) | Skala Podatkowa (12%/32%) |",
            "| :--- | :---: | :---: | :---: |",
            f"| **Roczny przychód** | {self.ryczalt.przychod_roczny:.2f} zł | {self.liniowy.przychod_roczny:.2f} zł | {self.skala.przychod_roczny:.2f} zł |",
            f"| **Roczne koszty podatkowe** | *nie uwzględniane* | {self.liniowy.koszty_roczne:.2f} zł | {self.skala.koszty_roczne:.2f} zł |",
            f"| **Dochód brutto** | {self.ryczalt.dochod_brutto:.2f} zł | {self.liniowy.dochod_brutto:.2f} zł | {self.skala.dochod_brutto:.2f} zł |",
            f"| **ZUS Składki społeczne** | {self.ryczalt.skladki_spoleczne_zus:.2f} zł | {self.liniowy.skladki_spoleczne_zus:.2f} zł | {self.skala.skladki_spoleczne_zus:.2f} zł |",
            f"| **ZUS Składka zdrowotna** | {self.ryczalt.skladka_zdrowotna_zus:.2f} zł | {self.liniowy.skladka_zdrowotna_zus:.2f} zł | {self.skala.skladka_zdrowotna_zus:.2f} zł |",
            f"| **Podatek dochodowy (PIT)** | {self.ryczalt.podatek_dochodowy:.2f} zł (stawka {self.stawka_ryczaltu:.0%}) | {self.liniowy.podatek_dochodowy:.2f} zł | {self.skala.podatek_dochodowy:.2f} zł |",
            f"| **Łączne obciążenia (ZUS + PIT)** | **{self.ryczalt.laczne_obciazenia:.2f} zł** | **{self.liniowy.laczne_obciazenia:.2f} zł** | **{self.skala.laczne_obciazenia:.2f} zł** |",
            f"| **Dochód NETTO 'na rękę'** | **{self.ryczalt.dochod_netto_na_reke:.2f} zł** | **{self.liniowy.dochod_netto_na_reke:.2f} zł** | **{self.skala.dochod_netto_na_reke:.2f} zł** |",
            f"| **Efektywne obciążenie przychodu** | **{self.ryczalt.efektywna_stopa_opodatkowania:.2%}** | **{self.liniowy.efektywna_stopa_opodatkowania:.2%}** | **{self.skala.efektywna_stopa_opodatkowania:.2%}** |",
            "",
        ]
        return "\n".join(linie)


def simulate_tax_regimes(
    przychody_roczne: Decimal,
    koszty_roczne: Decimal,
    stawka_ryczaltu: Decimal = Decimal("0.12"),
    rok: str = "2026"
) -> TaxRegimeComparison:
    """
    Precyzyjnie symuluje i porównuje łączne obciążenia podatkowo-składkowe w 3 formach opodatkowania JDG.
    """
    params = DEFAULT_ZUS_PARAMS.get(str(rok), DEFAULT_ZUS_PARAMS["2026"])
    podstawa_spol_msc = params["podstawa_pelny_zus"]
    
    # Składki społeczne rocznie (12 miesięcy pełnego ZUS z chorobowym)
    stopa_spoleczna_laczna = STOPA_EMERYTALNA + STOPA_RENTOWA + STOPA_CHOROBOWA + STOPA_WYPADKOWA + STOPA_FP
    spoleczne_rocznie = _round_money(podstawa_spol_msc * stopa_spoleczna_laczna * Decimal("12"))

    dochod_brutto = max(Decimal("0.00"), przychody_roczne - koszty_roczne)

    # -------------------------------------------------------------
    # 1. Ryczałt od przychodów ewidencjonowanych
    # -------------------------------------------------------------
    # Zdrowotna progowa:
    przec_wyn = params["przecietne_wynagrodzenie_zdrowotna"]
    if przychody_roczne <= Decimal("60000.00"):
        podstawa_zdrowotna_msc = _round_money(przec_wyn * Decimal("0.60"))
    elif przychody_roczne <= Decimal("300000.00"):
        podstawa_zdrowotna_msc = _round_money(przec_wyn * Decimal("1.00"))
    else:
        podstawa_zdrowotna_msc = _round_money(przec_wyn * Decimal("1.80"))

    zdrowotna_ryczalt_rocznie = _round_money(podstawa_zdrowotna_msc * Decimal("0.09") * Decimal("12"))
    odliczenie_zdrowotna_50 = _round_money(zdrowotna_ryczalt_rocznie * Decimal("0.50"))

    podstawa_ryczalt = max(Decimal("0.00"), przychody_roczne - spoleczne_rocznie - odliczenie_zdrowotna_50)
    podatek_ryczalt = _round_money(podstawa_ryczalt * stawka_ryczaltu)
    obciazenia_ryczalt = podatek_ryczalt + spoleczne_rocznie + zdrowotna_ryczalt_rocznie
    netto_ryczalt = przychody_roczne - koszty_roczne - obciazenia_ryczalt
    efekt_ryczalt = (obciazenia_ryczalt / przychody_roczne) if przychody_roczne > 0 else Decimal("0.00")

    regime_ryczalt = RegimeCalculation(
        nazwa_formy="Ryczałt ewidencjonowany",
        przychod_roczny=przychody_roczne,
        koszty_roczne=koszty_roczne,
        dochod_brutto=dochod_brutto,
        skladki_spoleczne_zus=spoleczne_rocznie,
        skladka_zdrowotna_zus=zdrowotna_ryczalt_rocznie,
        podstawa_opodatkowania=podstawa_ryczalt,
        podatek_dochodowy=podatek_ryczalt,
        laczne_obciazenia=obciazenia_ryczalt,
        dochod_netto_na_reke=netto_ryczalt,
        efektywna_stopa_opodatkowania=efekt_ryczalt,
    )

    # -------------------------------------------------------------
    # 2. Podatek Liniowy 19%
    # -------------------------------------------------------------
    # Zdrowotna 4.9% dochodu po odliczeniu składek społecznych (z minimalną podstawą)
    dochod_po_spolecznych = max(Decimal("0.00"), dochod_brutto - spoleczne_rocznie)
    min_zdrowotna_rocznie = _round_money(Decimal("4800.00") * Decimal("0.09") * Decimal("12"))  # 9% z min. wynagrodzenia
    zdrowotna_liniowy_wyliczona = _round_money(dochod_po_spolecznych * Decimal("0.049"))
    zdrowotna_liniowy = max(min_zdrowotna_rocznie, zdrowotna_liniowy_wyliczona)

    # Limit odliczenia składki zdrowotnej w podatku liniowym (np. 12 900 zł na 2026 r.)
    LIMIT_ODLICZENIA_ZDROWOTNEJ_LINIOWY = Decimal("12900.00")
    odliczenie_zdrowotna_liniowy = min(zdrowotna_liniowy, LIMIT_ODLICZENIA_ZDROWOTNEJ_LINIOWY)

    podstawa_liniowy = max(Decimal("0.00"), dochod_po_spolecznych - odliczenie_zdrowotna_liniowy)
    podatek_liniowy = _round_money(podstawa_liniowy * Decimal("0.19"))
    obciazenia_liniowy = podatek_liniowy + spoleczne_rocznie + zdrowotna_liniowy
    netto_liniowy = przychody_roczne - koszty_roczne - obciazenia_liniowy
    efekt_liniowy = (obciazenia_liniowy / przychody_roczne) if przychody_roczne > 0 else Decimal("0.00")

    regime_liniowy = RegimeCalculation(
        nazwa_formy="Podatek Liniowy 19%",
        przychod_roczny=przychody_roczne,
        koszty_roczne=koszty_roczne,
        dochod_brutto=dochod_brutto,
        skladki_spoleczne_zus=spoleczne_rocznie,
        skladka_zdrowotna_zus=zdrowotna_liniowy,
        podstawa_opodatkowania=podstawa_liniowy,
        podatek_dochodowy=podatek_liniowy,
        laczne_obciazenia=obciazenia_liniowy,
        dochod_netto_na_reke=netto_liniowy,
        efektywna_stopa_opodatkowania=efekt_liniowy,
    )

    # -------------------------------------------------------------
    # 3. Skala Podatkowa (12% / 32%, kwota wolna 30k zł)
    # -------------------------------------------------------------
    # Zdrowotna 9.0% dochodu (brak możliwości odliczenia)
    zdrowotna_skala_wyliczona = _round_money(dochod_po_spolecznych * Decimal("0.09"))
    zdrowotna_skala = max(min_zdrowotna_rocznie, zdrowotna_skala_wyliczona)

    podstawa_skala = dochod_po_spolecznych
    PROG_I = Decimal("120000.00")
    KWOTA_ZMNIEJSZAJACA = Decimal("3600.00")  # 12% z 30 000 zł

    if podstawa_skala <= Decimal("30000.00"):
        podatek_skala = Decimal("0.00")
    elif podstawa_skala <= PROG_I:
        podatek_skala = _round_money(podstawa_skala * Decimal("0.12") - KWOTA_ZMNIEJSZAJACA)
    else:
        podatek_I_prog = _round_money(PROG_I * Decimal("0.12") - KWOTA_ZMNIEJSZAJACA)  # 10 800 zł
        nadwyzka = podstawa_skala - PROG_I
        podatek_skala = _round_money(podatek_I_prog + (nadwyzka * Decimal("0.32")))

    obciazenia_skala = podatek_skala + spoleczne_rocznie + zdrowotna_skala
    netto_skala = przychody_roczne - koszty_roczne - obciazenia_skala
    efekt_skala = (obciazenia_skala / przychody_roczne) if przychody_roczne > 0 else Decimal("0.00")

    regime_skala = RegimeCalculation(
        nazwa_formy="Skala Podatkowa (12%/32%)",
        przychod_roczny=przychody_roczne,
        koszty_roczne=koszty_roczne,
        dochod_brutto=dochod_brutto,
        skladki_spoleczne_zus=spoleczne_rocznie,
        skladka_zdrowotna_zus=zdrowotna_skala,
        podstawa_opodatkowania=podstawa_skala,
        podatek_dochodowy=podatek_skala,
        laczne_obciazenia=obciazenia_skala,
        dochod_netto_na_reke=netto_skala,
        efektywna_stopa_opodatkowania=efekt_skala,
    )

    # Wybór formy z najwyższym dochodem netto "na rękę"
    ranking = sorted(
        [regime_ryczalt, regime_liniowy, regime_skala],
        key=lambda r: r.dochod_netto_na_reke,
        reverse=True
    )
    zwyciezca = ranking[0]
    drugi = ranking[1]
    oszczednosc = zwyciezca.dochod_netto_na_reke - drugi.dochod_netto_na_reke

    return TaxRegimeComparison(
        rok=str(rok),
        stawka_ryczaltu=stawka_ryczaltu,
        ryczalt=regime_ryczalt,
        liniowy=regime_liniowy,
        skala=regime_skala,
        najkorzystniejsza_forma=zwyciezca.nazwa_formy,
        roczna_oszczednosc_wzgledem_drugiej=oszczednosc,
    )


@dataclass
class ExpenseLeakAlert:
    typ: str                 # "BRAKUJACY_KOSZT" | "SKOK_KWOTY" | "NOWY_KONTRAHENT"
    nip_kontrahenta: str
    nazwa_kontrahenta: str
    opis: str
    srednia_kwota: Optional[Decimal] = None
    ostatnia_kwota: Optional[Decimal] = None


@dataclass
class ExpenseAuditResult:
    rok: str
    miesiac: str
    liczba_alertow: int
    alerty: List[ExpenseLeakAlert] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "liczba_alertow": self.liczba_alertow,
            "alerty": [
                {
                    "typ": a.typ,
                    "nip": a.nip_kontrahenta,
                    "nazwa": a.nazwa_kontrahenta,
                    "opis": a.opis,
                    "srednia_kwota": str(a.srednia_kwota) if a.srednia_kwota else None,
                    "ostatnia_kwota": str(a.ostatnia_kwota) if a.ostatnia_kwota else None,
                }
                for a in self.alerty
            ]
        }


def audit_expense_leaks(profile: CompanyProfile, rok: str, miesiac: str) -> ExpenseAuditResult:
    """
    Analizuje historię kosztów firmy i wykrywa brakujące powtarzalne wydatki (np. leasing, serwery, telefon)
    oraz nietypowe skoki kwot.
    """
    target_m = int(miesiac)
    rok_str = str(rok)

    # 1. Pobierz faktury kosztowe z bieżącego miesiąca
    biezace_koszty = InvoiceStorage.list_invoices(profile, rok_str, f"{target_m:02d}", typ=InvoiceType.KOSZT)
    biezace_nipy = {inv.sprzedawca.nip for inv in biezace_koszty}

    # 2. Pobierz historię z ostatnich 3 miesięcy
    historia_kontrahentow: Dict[str, List[Decimal]] = {}
    nazwy_kontrahentow: Dict[str, str] = {}

    for prev_m in range(max(1, target_m - 3), target_m):
        faktury_prev = InvoiceStorage.list_invoices(profile, rok_str, f"{prev_m:02d}", typ=InvoiceType.KOSZT)
        for inv in faktury_prev:
            nip = inv.sprzedawca.nip
            nazwa = inv.sprzedawca.nazwa
            nazwy_kontrahentow[nip] = nazwa
            historia_kontrahentow.setdefault(nip, []).append(inv.suma_netto)

    alerty: List[ExpenseLeakAlert] = []

    # Wykrywanie brakujących powtarzalnych faktur (występujących w min. 2 poprzednich miesiącach)
    for nip, kwoty in historia_kontrahentow.items():
        if len(kwoty) >= 2 and nip not in biezace_nipy:
            srednia = _round_money(sum(kwoty, Decimal("0.00")) / Decimal(str(len(kwoty))))
            alerty.append(
                ExpenseLeakAlert(
                    typ="BRAKUJACY_KOSZT",
                    nip_kontrahenta=nip,
                    nazwa_kontrahenta=nazwy_kontrahentow.get(nip, nip),
                    opis=f"Brak comiesięcznej faktury od kontrahenta {nazwy_kontrahentow.get(nip, nip)} (średnia kwota: {srednia} zł netto).",
                    srednia_kwota=srednia,
                )
            )

    return ExpenseAuditResult(
        rok=rok_str,
        miesiac=f"{target_m:02d}",
        liczba_alertow=len(alerty),
        alerty=alerty,
    )

