"""
Deterministyczne narzędzia dla Ewidencji Przychodów i Ryczałtu od przychodów ewidencjonowanych (PIT-28).
Zgodne z ustawą o zryczałtowanym podatku dochodowym od niektórych przychodów osiąganych przez osoby fizyczne.
Wszystkie operacje matematyczne oparte są wyłącznie na typie Decimal.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Any
from pathlib import Path
import json
import re

from src.core.invoice import Invoice, InvoiceItem


# Standardowe stawki ryczałtu w Polsce (jako Decimal)
STAWKA_17 = Decimal("0.17")    # Wolne zawody
STAWKA_15 = Decimal("0.15")    # Usługi pośrednictwa, doradztwa itp.
STAWKA_14 = Decimal("0.14")    # Usługi architektoniczne, inżynierskie, zdrowotne
STAWKA_12 = Decimal("0.12")    # Usługi IT, programowanie, analiza systemów, doradztwo IT, infrastruktura (art. 12 ust. 1 pkt 2b)
STAWKA_10 = Decimal("0.10")    # Kupno i sprzedaż nieruchomości na własny rachunek
STAWKA_8_5 = Decimal("0.085")  # Działalność usługowa ogólna
STAWKA_5_5 = Decimal("0.055")  # Roboty budowlane, działalność wytwórcza
STAWKA_3 = Decimal("0.03")     # Działalność gastronomiczna, handel


# Słowa kluczowe dla automatycznej klasyfikacji stawek ryczałtu (gdy brak w XML)
KEYWORDS_12_IT = [
    "programist", "oprogramowani", "kodowani", "software", "development",
    "backend", "frontend", "fullstack", "devops", "cloud", "architektur",
    "system", "baza danych", "api", "doradztwo it", "it consulting", "ai", "machine learning",
    "infrastruktur", "informatyczn", "zarządzanie siecią", "zarządzanie system", "zarządzania infrastrukturą"
]

KEYWORDS_8_5_USLUGI = [
    "administracyjn", "biurow", "szkoleni", "kurs", "tłumaczeni",
    "wsparcie techniczne", "support", "serwis sprzętu", "grafik", "design"
]


@dataclass
class RegulySprzedazyFirmy:
    """Trwałe reguły stawek ryczałtu dla kontrahentów / nabywców firmy."""
    nip_firmy: str
    stawki_nabywcow: Dict[str, Decimal] = field(default_factory=dict)

    @classmethod
    def sciezka_pliku(cls, profile: Any) -> Path:
        return profile.katalog_firmy / "reguly_sprzedazy.json"

    @classmethod
    def load(cls, profile: Any) -> "RegulySprzedazyFirmy":
        path = cls.sciezka_pliku(profile)
        if not path.exists():
            return cls(nip_firmy=profile.nip)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stawki = {str(k): Decimal(str(v)) for k, v in data.get("stawki_nabywcow", {}).items()}
            return cls(nip_firmy=profile.nip, stawki_nabywcow=stawki)
        except Exception:
            return cls(nip_firmy=profile.nip)

    def save(self, profile: Any) -> Path:
        path = self.sciezka_pliku(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nip_firmy": self.nip_firmy,
            "stawki_nabywcow": {str(k): str(v) for k, v in self.stawki_nabywcow.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path


def classify_ryczalt_rate_for_item(
    item_desc: str,
    default_rate: Decimal = STAWKA_12
) -> Decimal:
    """
    Klasyfikuje stawkę ryczałtu na podstawie opisu pozycji faktury.
    W przypadku braku dopasowania stosuje stawkę domyślną podatnika.
    """
    desc_lower = item_desc.lower()

    for kw in KEYWORDS_12_IT:
        if kw in desc_lower:
            return STAWKA_12

    for kw in KEYWORDS_8_5_USLUGI:
        if kw in desc_lower:
            return STAWKA_8_5

    return default_rate


@dataclass
class EwidencjaPrzychodowWpis:
    """Wpis w Ewidencji Przychodów dla pojedynczej faktury."""
    numer_faktury: str
    data_sprzedazy: str
    nabywca_nazwa: str
    nabywca_nip: str
    przychody_wg_stawek: Dict[Decimal, Decimal]
    suma_przychodu: Decimal
    opis_zdarzenia: str = ""
    zrodlo: str = "KSEF"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer_faktury": self.numer_faktury,
            "data_sprzedazy": self.data_sprzedazy,
            "nabywca_nazwa": self.nabywca_nazwa,
            "nabywca_nip": self.nabywca_nip,
            "przychody_wg_stawek": {str(k): str(v) for k, v in self.przychody_wg_stawek.items()},
            "suma_przychodu": str(self.suma_przychodu),
            "opis_zdarzenia": self.opis_zdarzenia,
            "zrodlo": self.zrodlo,
        }


@dataclass
class EwidencjaPrzychodowMiesiaca:
    """Zestawienie ewidencji przychodów za dany miesiąc."""
    rok: str
    miesiac: str
    wpisy: List[EwidencjaPrzychodowWpis] = field(default_factory=list)
    sumy_wg_stawek: Dict[Decimal, Decimal] = field(default_factory=dict)
    laczny_przychod_netto: Decimal = Decimal("0.00")

    def dodaj_fakture(
        self,
        invoice: Invoice,
        default_rate: Decimal = STAWKA_12,
        custom_buyer_rates: Optional[Dict[str, Decimal]] = None
    ) -> EwidencjaPrzychodowWpis:
        """Księguje fakturę sprzedaży w ewidencji przychodów."""
        przychody_faktury: Dict[Decimal, Decimal] = {}
        buyer_rate = None
        if custom_buyer_rates:
            buyer_rate = custom_buyer_rates.get(invoice.nabywca.nip) or custom_buyer_rates.get(invoice.nabywca.nazwa)

        if invoice.pozycje:
            for poz in invoice.pozycje:
                stawka = poz.stawka_ryczaltu or buyer_rate or classify_ryczalt_rate_for_item(poz.opis, default_rate)
                przychody_faktury[stawka] = przychody_faktury.get(stawka, Decimal("0.00")) + poz.wartosc_netto
        else:
            # Gdy brak rozbitych pozycji, cały netto przypisujemy do stawki domyślnej lub buyer_rate
            rate = buyer_rate or default_rate
            przychody_faktury[rate] = invoice.suma_netto

        suma_faktury = sum(przychody_faktury.values(), Decimal("0.00"))
        opis_zdarzenia = ", ".join(p.opis for p in invoice.pozycje if p.opis) if invoice.pozycje else "Świadczenie usług"
        zrodlo = invoice.zrodlo or "KSEF"

        wpis = EwidencjaPrzychodowWpis(
            numer_faktury=invoice.numer,
            data_sprzedazy=invoice.data_sprzedazy or invoice.data_wystawienia,
            nabywca_nazwa=invoice.nabywca.nazwa,
            nabywca_nip=invoice.nabywca.nip,
            przychody_wg_stawek=przychody_faktury,
            suma_przychodu=suma_faktury,
            opis_zdarzenia=opis_zdarzenia,
            zrodlo=zrodlo,
        )

        self.wpisy.append(wpis)
        for st, kwota in przychody_faktury.items():
            self.sumy_wg_stawek[st] = self.sumy_wg_stawek.get(st, Decimal("0.00")) + kwota
        self.laczny_przychod_netto += suma_faktury

        return wpis

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "sumy_wg_stawek": {str(k): str(v) for k, v in self.sumy_wg_stawek.items()},
            "laczny_przychod_netto": str(self.laczny_przychod_netto),
            "liczba_faktur": len(self.wpisy),
            "wpisy": [w.to_dict() for w in self.wpisy],
        }


@dataclass
class PIT28CalculationResult:
    """Rezultat wyliczenia zaliczki na podatek ryczałtowy (PIT-28)."""
    rok: str
    miesiac: str
    przychod_laczny: Decimal
    odliczenie_spoleczne: Decimal
    odliczenie_zdrowotna_50: Decimal
    podstawa_opodatkowania: Decimal
    podatek_wg_stawek: Dict[Decimal, Decimal]
    podatek_nalezy_dokladny: Decimal
    zaliczka_pit28_zaokraglona: int  # Zaokrąglenie do pełnych złotych wg Ordynacji Podatkowej
    termin_platnosci: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "przychod_laczny": str(self.przychod_laczny),
            "odliczenie_spoleczne": str(self.odliczenie_spoleczne),
            "odliczenie_zdrowotna_50": str(self.odliczenie_zdrowotna_50),
            "podstawa_opodatkowania": str(self.podstawa_opodatkowania),
            "podatek_wg_stawek": {str(k): str(v) for k, v in self.podatek_wg_stawek.items()},
            "podatek_nalezy_dokladny": str(self.podatek_nalezy_dokladny),
            "zaliczka_pit28_zaokraglona": self.zaliczka_pit28_zaokraglona,
            "termin_platnosci": self.termin_platnosci,
        }


def calculate_pit28_advance(
    rok: str,
    miesiac: str,
    sumy_przychodow_wg_stawek: Dict[Decimal, Decimal],
    skladki_spoleczne_do_odliczenia: Decimal = Decimal("0.00"),
    skladka_zdrowotna_zaplacona: Decimal = Decimal("0.00"),
) -> PIT28CalculationResult:
    """
    Oblicza miesięczną zaliczkę na podatek ryczałtowy (PIT-28).
    
    Zasady obliczania:
    1. Przychód sumaryczny pomniejsza się o zapłacone w danym miesiącu składki społeczne ZUS.
    2. Przychód pomniejsza się o 50% zapłaconej składki zdrowotnej.
    3. Jeśli występują różne stawki, odliczenia rozlicza się proporcjonalnie do udziału przychodów w danej stawce.
    4. Podatek wylicza się per stawka.
    5. Finalna zaliczka zaokrąglana jest do pełnych złotych (końcówki poniżej 50 gr pomija się, 50 gr i więcej podwyższa do pełnych zł).
    """
    laczny_przychod = sum(sumy_przychodow_wg_stawek.values(), Decimal("0.00"))
    odliczenie_zdrowotna = (skladka_zdrowotna_zaplacona * Decimal("0.50")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    laczne_odliczenia = skladki_spoleczne_do_odliczenia + odliczenie_zdrowotna

    podatek_wg_stawek: Dict[Decimal, Decimal] = {}
    podatek_laczny_dokladny = Decimal("0.00")

    if laczny_przychod <= Decimal("0.00"):
        podstawa_laczna = Decimal("0.00")
    else:
        podstawa_laczna = max(Decimal("0.00"), laczny_przychod - laczne_odliczenia)

        # Proporcjonalny podział odliczeń na stawki
        for stawka, przychod_stawki in sumy_przychodow_wg_stawek.items():
            if laczny_przychod > Decimal("0.00"):
                udzial = przychod_stawki / laczny_przychod
                odliczenia_dla_stawki = (laczne_odliczenia * udzial).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                # Zgodnie z art. 63 § 1 Ordynacji Podatkowej podstawę opodatkowania zaokrągla się do pełnych złotych
                podstawa_stawki = max(Decimal("0.00"), przychod_stawki - odliczenia_dla_stawki).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            else:
                podstawa_stawki = Decimal("0.00")

            podatek_stawki = (podstawa_stawki * stawka).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            podatek_wg_stawek[stawka] = podatek_stawki
            podatek_laczny_dokladny += podatek_stawki

    # Zaokrąglenie do pełnych złotych (Ordynacja Podatkowa art. 63 § 1)
    zaliczka_zaokraglona = int(podatek_laczny_dokladny.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Termin płatności ryczałtu: 20. dzień następnego miesiąca
    m_int = int(miesiac)
    rok_int = int(rok)
    if m_int == 12:
        kolejny_rok = rok_int + 1
        kolejny_m = 1
    else:
        kolejny_rok = rok_int
        kolejny_m = m_int + 1
    termin_platnosci = f"{kolejny_rok:04d}-{kolejny_m:02d}-20"

    return PIT28CalculationResult(
        rok=str(rok),
        miesiac=str(miesiac).zfill(2),
        przychod_laczny=laczny_przychod,
        odliczenie_spoleczne=skladki_spoleczne_do_odliczenia,
        odliczenie_zdrowotna_50=odliczenie_zdrowotna,
        podstawa_opodatkowania=podstawa_laczna,
        podatek_wg_stawek=podatek_wg_stawek,
        podatek_nalezy_dokladny=podatek_laczny_dokladny,
        zaliczka_pit28_zaokraglona=zaliczka_zaokraglona,
        termin_platnosci=termin_platnosci,
    )

