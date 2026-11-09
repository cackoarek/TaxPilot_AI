"""
Deterministyczny kalkulator składek ZUS dla JDG w Polsce.
Zgodny z przepisami na lata 2025/2026.
Arytmetyka oparta wyłącznie na typie Decimal.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional

from src.core.company import TypZUS, FormaOpodatkowania


# Domyślne wskaźniki makroekonomiczne
# 2026: Prognozowane przeciętne wynagrodzenie do składek społecznych (60% z ~8840 zł = 5304.00 zł)
# Przeciętne wynagrodzenie w sektorze przedsiębiorstw w IV kw. do zdrowotnej (~9200.00 zł)
DEFAULT_ZUS_PARAMS = {
    "2026": {
        "podstawa_pelny_zus": Decimal("5304.00"),
        "podstawa_preferencyjny_zus": Decimal("1440.00"),  # 30% z płacy minimalnej (szac. 4800 zł)
        "przecietne_wynagrodzenie_zdrowotna": Decimal("9200.00"),
    },
    "2025": {
        "podstawa_pelny_zus": Decimal("4694.40"),
        "podstawa_preferencyjny_zus": Decimal("1399.80"),
        "przecietne_wynagrodzenie_zdrowotna": Decimal("8500.00"),
    }
}

# Stopy procentowe składek społecznych
STOPA_EMERYTALNA = Decimal("0.1952")  # 19.52%
STOPA_RENTOWA = Decimal("0.0800")     # 8.00%
STOPA_CHOROBOWA = Decimal("0.0245")   # 2.45% (dobrowolna)
STOPA_WYPADKOWA = Decimal("0.0167")   # 1.67% (standardowa dla małych firm do 9 ubezpieczonych)
STOPA_FP = Decimal("0.0245")          # 2.45% (Fundusz Pracy i Fundusz Solidarnościowy)
STOPA_ZDROWOTNA = Decimal("0.0900")   # 9.00%


def _round_money(value: Decimal) -> Decimal:
    """Zaokrągla kwotę do 2 miejsc po przecinku (pół w górę)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ZUSCalculationResult:
    rok: str
    miesiac: str
    typ_zus: TypZUS
    chorobowe_dobrowolne: bool
    forma_opodatkowania: FormaOpodatkowania
    
    # Składki społeczne
    podstawa_spoleczne: Decimal
    emerytalna: Decimal
    rentowa: Decimal
    chorobowa: Decimal
    wypadkowa: Decimal
    fundusz_pracy: Decimal
    suma_spoleczne: Decimal

    # Składka zdrowotna
    prog_przychodow_zdrowotna: str  # "<60k" | "60k-300k" | ">300k"
    podstawa_zdrowotna: Decimal
    zdrowotna: Decimal
    odliczenie_zdrowotna_ryczalt_50: Decimal  # 50% zapłaconej zdrowotnej odliczane od przychodu na ryczałcie

    # Łącznie do zapłaty do ZUS (jeden przelew na mikrorachunek ZUS - NRS)
    lacznie_do_zaplaty: Decimal
    termin_platnosci: str  # np. "2026-02-20" dla rozliczenia za styczeń 2026

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "typ_zus": self.typ_zus.value,
            "chorobowe_dobrowolne": self.chorobowe_dobrowolne,
            "forma_opodatkowania": self.forma_opodatkowania.value,
            "podstawa_spoleczne": str(self.podstawa_spoleczne),
            "skladki_spoleczne": {
                "emerytalna": str(self.emerytalna),
                "rentowa": str(self.rentowa),
                "chorobowa": str(self.chorobowa),
                "wypadkowa": str(self.wypadkowa),
                "fundusz_pracy": str(self.fundusz_pracy),
                "suma": str(self.suma_spoleczne),
            },
            "skladka_zdrowotna": {
                "prog": self.prog_przychodow_zdrowotna,
                "podstawa": str(self.podstawa_zdrowotna),
                "kwota": str(self.zdrowotna),
                "odliczenie_ryczalt_50": str(self.odliczenie_zdrowotna_ryczalt_50),
            },
            "lacznie_do_zaplaty": str(self.lacznie_do_zaplaty),
            "termin_platnosci": self.termin_platnosci,
        }


def calculate_zus(
    rok: str,
    miesiac: str,
    typ_zus: TypZUS = TypZUS.PELNY_ZUS,
    chorobowe_dobrowolne: bool = True,
    forma_opodatkowania: FormaOpodatkowania = FormaOpodatkowania.RYCZALT,
    przychod_roczny_narastajaco: Decimal = Decimal("0.00"),
    custom_podstawa_spoleczne: Optional[Decimal] = None,
    custom_przecietne_wynagrodzenie: Optional[Decimal] = None,
) -> ZUSCalculationResult:
    """
    Deterministycznie oblicza komplet składek ZUS (społeczne + zdrowotna) dla danego miesiąca.
    
    Args:
        rok: Rok podatkowy (np. "2026")
        miesiac: Miesiąc rozliczeniowy ("01" do "12")
        typ_zus: Typ opłacanych składek (PELNY_ZUS, ULGA_NA_START, MALY_ZUS_PLUS)
        chorobowe_dobrowolne: Czy przedsiębiorca zgłosił się do ubezpieczenia chorobowego
        forma_opodatkowania: Forma opodatkowania (RYCZALT, LINIOWY, SKALA)
        przychod_roczny_narastajaco: Suma przychodów od początku roku do danego miesiąca (do progów zdrowotnej na ryczałcie)
        custom_podstawa_spoleczne: Opcjonalne ręczne nadpisanie podstawy składek społecznych
        custom_przecietne_wynagrodzenie: Opcjonalne ręczne nadpisanie przeciętnego wynagrodzenia do zdrowotnej
    """
    params = DEFAULT_ZUS_PARAMS.get(str(rok), DEFAULT_ZUS_PARAMS["2026"])

    # 1. Wyznaczenie podstawy składek społecznych
    if typ_zus == TypZUS.ULGA_NA_START:
        podstawa_spol = Decimal("0.00")
        emerytalna = Decimal("0.00")
        rentowa = Decimal("0.00")
        chorobowa = Decimal("0.00")
        wypadkowa = Decimal("0.00")
        fundusz_pracy = Decimal("0.00")
    elif typ_zus == TypZUS.MALY_ZUS_PLUS:
        podstawa_spol = custom_podstawa_spoleczne or params["podstawa_preferencyjny_zus"]
        emerytalna = _round_money(podstawa_spol * STOPA_EMERYTALNA)
        rentowa = _round_money(podstawa_spol * STOPA_RENTOWA)
        chorobowa = _round_money(podstawa_spol * STOPA_CHOROBOWA) if chorobowe_dobrowolne else Decimal("0.00")
        wypadkowa = _round_money(podstawa_spol * STOPA_WYPADKOWA)
        # Przy preferencyjnym ZUS podstawa jest niższa niż minimalne wynagrodzenie -> brak FP
        fundusz_pracy = Decimal("0.00")
    else:  # PELNY_ZUS
        podstawa_spol = custom_podstawa_spoleczne or params["podstawa_pelny_zus"]
        emerytalna = _round_money(podstawa_spol * STOPA_EMERYTALNA)
        rentowa = _round_money(podstawa_spol * STOPA_RENTOWA)
        chorobowa = _round_money(podstawa_spol * STOPA_CHOROBOWA) if chorobowe_dobrowolne else Decimal("0.00")
        wypadkowa = _round_money(podstawa_spol * STOPA_WYPADKOWA)
        fundusz_pracy = _round_money(podstawa_spol * STOPA_FP)

    suma_spoleczne = emerytalna + rentowa + chorobowa + wypadkowa + fundusz_pracy

    # 2. Składka zdrowotna
    przecietne_wynagrodzenie = custom_przecietne_wynagrodzenie or params["przecietne_wynagrodzenie_zdrowotna"]

    if forma_opodatkowania == FormaOpodatkowania.RYCZALT:
        # Progi przychodu narastająco w roku podatkowym dla ryczałtu:
        # I próg: do 60 000 zł -> 60% przeciętnego wynagrodzenia
        # II próg: 60 000 zł do 300 000 zł -> 100% przeciętnego wynagrodzenia
        # III próg: powyżej 300 000 zł -> 180% przeciętnego wynagrodzenia
        if przychod_roczny_narastajaco <= Decimal("60000.00"):
            prog_str = "<60k"
            mnoznik = Decimal("0.60")
        elif przychod_roczny_narastajaco <= Decimal("300000.00"):
            prog_str = "60k-300k"
            mnoznik = Decimal("1.00")
        else:
            prog_str = ">300k"
            mnoznik = Decimal("1.80")

        podstawa_zdrowotna = _round_money(przecietne_wynagrodzenie * mnoznik)
        zdrowotna = _round_money(podstawa_zdrowotna * STOPA_ZDROWOTNA)
        odliczenie_zdrowotna_50 = _round_money(zdrowotna * Decimal("0.50"))
    else:
        # Domyślnie uproszczenie dla pozostałych form (liniowy 4.9%, skala 9%)
        podstawa_zdrowotna = przecietne_wynagrodzenie
        zdrowotna = _round_money(podstawa_zdrowotna * STOPA_ZDROWOTNA)
        odliczenie_zdrowotna_50 = Decimal("0.00")
        prog_str = "liniowy/skala"

    lacznie_do_zaplaty = suma_spoleczne + zdrowotna

    # Termin płatności ZUS dla JDG: 20. dzień kolejnego miesiąca
    m_int = int(miesiac)
    rok_int = int(rok)
    if m_int == 12:
        kolejny_rok = rok_int + 1
        kolejny_miesiac = 1
    else:
        kolejny_rok = rok_int
        kolejny_miesiac = m_int + 1
    termin_platnosci = f"{kolejny_rok:04d}-{kolejny_miesiac:02d}-20"

    return ZUSCalculationResult(
        rok=str(rok),
        miesiac=str(miesiac).zfill(2),
        typ_zus=typ_zus,
        chorobowe_dobrowolne=chorobowe_dobrowolne,
        forma_opodatkowania=forma_opodatkowania,
        podstawa_spoleczne=podstawa_spol,
        emerytalna=emerytalna,
        rentowa=rentowa,
        chorobowa=chorobowa,
        wypadkowa=wypadkowa,
        fundusz_pracy=fundusz_pracy,
        suma_spoleczne=suma_spoleczne,
        prog_przychodow_zdrowotna=prog_str,
        podstawa_zdrowotna=podstawa_zdrowotna,
        zdrowotna=zdrowotna,
        odliczenie_zdrowotna_ryczalt_50=odliczenie_zdrowotna_50,
        lacznie_do_zaplaty=lacznie_do_zaplaty,
        termin_platnosci=termin_platnosci,
    )

