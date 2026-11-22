"""
Deterministyczne narzędzia dla Rejestru Sprzedaży i Zakupów VAT oraz rozliczenia JPK_V7.
Zgodne z ustawą o podatku od towarów i usług (ustawa o VAT).
Wszystkie operacje matematyczne oparte są wyłącznie na typie Decimal.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.invoice import Invoice


class ProporcjaOdliczeniaVAT(Decimal, Enum):
    PELNE = Decimal("1.00")  # 100% - wydatki firmowe bieżące (serwery, sprzęt, biuro)
    SAMOCHOD_MIESZANY = Decimal("0.50")  # 50% - pojazdy osobowe w trybie mieszanym (art. 86a ustawy o VAT)
    BRAK = Decimal("0.00")  # 0% - brak prawa do odliczenia (np. usługi gastronomiczne, noclegowe)


# Słowa kluczowe dla autodetekcji wydatków samochodowych (50% VAT)
KEYWORDS_SAMOCHOD_50 = [
    "paliwo",
    "benzyn",
    "diesel",
    "lpg",
    "olej napędow",
    "stacja paliw",
    "myjnia",
    "serwis auta",
    "naprawa pojazdu",
    "opon",
    "wulkanizacj",
    "leasing auta",
    "leasing operacyjny samochodu",
    "parking",
    "autostrad",
]

# Słowa kluczowe dla braku prawa do odliczenia (art. 88 ustawy o VAT)
KEYWORDS_BRAK_ODLICZENIA_0 = ["usługa noclegowa", "nocleg", "hotel", "gastronomi", "restauracj"]


def classify_vat_deduction_ratio(
    item_desc: str, default_ratio: ProporcjaOdliczeniaVAT = ProporcjaOdliczeniaVAT.PELNE
) -> ProporcjaOdliczeniaVAT:
    """
    Automatycznie klasyfikuje współczynnik odliczenia VAT na podstawie opisu wydatku.
    """
    desc_lower = item_desc.lower()

    for kw in KEYWORDS_BRAK_ODLICZENIA_0:
        if kw in desc_lower:
            return ProporcjaOdliczeniaVAT.BRAK

    for kw in KEYWORDS_SAMOCHOD_50:
        if kw in desc_lower:
            return ProporcjaOdliczeniaVAT.SAMOCHOD_MIESZANY

    return default_ratio


@dataclass
class RejestrSprzedazyWpis:
    numer_faktury: str
    data_sprzedazy: str
    nabywca_nazwa: str
    nabywca_nip: str
    netto_wg_stawek: Dict[str, Decimal]
    vat_wg_stawek: Dict[str, Decimal]
    suma_netto: Decimal
    suma_vat: Decimal
    suma_brutto: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer_faktury": self.numer_faktury,
            "data_sprzedazy": self.data_sprzedazy,
            "nabywca_nazwa": self.nabywca_nazwa,
            "nabywca_nip": self.nabywca_nip,
            "netto_wg_stawek": {k: str(v) for k, v in self.netto_wg_stawek.items()},
            "vat_wg_stawek": {k: str(v) for k, v in self.vat_wg_stawek.items()},
            "suma_netto": str(self.suma_netto),
            "suma_vat": str(self.suma_vat),
            "suma_brutto": str(self.suma_brutto),
        }


@dataclass
class RejestrZakupowWpis:
    numer_faktury: str
    data_zakupu: str
    sprzedawca_nazwa: str
    sprzedawca_nip: str
    suma_netto: Decimal
    suma_vat_z_faktury: Decimal
    proporcja_odliczenia: ProporcjaOdliczeniaVAT
    vat_naliczony_do_odliczenia: Decimal
    vat_nieodliczony: Decimal
    suma_brutto: Decimal
    odrzucone_netto_prywatne: Decimal = Decimal("0.00")
    odrzucony_vat_prywatny: Decimal = Decimal("0.00")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer_faktury": self.numer_faktury,
            "data_zakupu": self.data_zakupu,
            "sprzedawca_nazwa": self.sprzedawca_nazwa,
            "sprzedawca_nip": self.sprzedawca_nip,
            "suma_netto": str(self.suma_netto),
            "suma_vat_z_faktury": str(self.suma_vat_z_faktury),
            "proporcja_odliczenia": str(self.proporcja_odliczenia.value),
            "vat_naliczony_do_odliczenia": str(self.vat_naliczony_do_odliczenia),
            "vat_nieodliczony": str(self.vat_nieodliczony),
            "odrzucone_netto_prywatne": str(self.odrzucone_netto_prywatne),
            "odrzucony_vat_prywatny": str(self.odrzucony_vat_prywatny),
            "suma_brutto": str(self.suma_brutto),
        }


@dataclass
class RejestrVATMiesiaca:
    rok: str
    miesiac: str
    wpisy_sprzedazy: List[RejestrSprzedazyWpis] = field(default_factory=list)
    wpisy_zakupow: List[RejestrZakupowWpis] = field(default_factory=list)

    # Sumy sprzedaży (VAT należny)
    suma_sprzedaz_netto: Decimal = Decimal("0.00")
    suma_sprzedaz_vat_nalezy: Decimal = Decimal("0.00")
    suma_sprzedaz_brutto: Decimal = Decimal("0.00")
    sprzedaz_netto_wg_stawek: Dict[str, Decimal] = field(default_factory=dict)
    sprzedaz_vat_wg_stawek: Dict[str, Decimal] = field(default_factory=dict)

    # Sumy zakupów (VAT naliczony)
    suma_zakupy_netto: Decimal = Decimal("0.00")
    suma_zakupy_vat_faktury: Decimal = Decimal("0.00")
    suma_zakupy_vat_naliczony_odliczenie: Decimal = Decimal("0.00")
    suma_zakupy_vat_nieodliczony: Decimal = Decimal("0.00")
    suma_zakupy_brutto: Decimal = Decimal("0.00")
    suma_zakupy_odrzucone_netto_prywatne: Decimal = Decimal("0.00")
    suma_zakupy_odrzucony_vat_prywatny: Decimal = Decimal("0.00")

    def dodaj_fakture_sprzedazy(self, invoice: Invoice) -> RejestrSprzedazyWpis:
        """Księguje fakturę w rejestrze sprzedaży VAT."""
        netto_stawek: Dict[str, Decimal] = {}
        vat_stawek: Dict[str, Decimal] = {}

        if invoice.stawki_netto and invoice.stawki_vat:
            netto_stawek = dict(invoice.stawki_netto)
            vat_stawek = dict(invoice.stawki_vat)
        elif invoice.pozycje:
            for p in invoice.pozycje:
                st = p.stawka_vat
                netto_stawek[st] = netto_stawek.get(st, Decimal("0.00")) + p.wartosc_netto
                vat_stawek[st] = vat_stawek.get(st, Decimal("0.00")) + p.kwota_vat
        else:
            netto_stawek["23"] = invoice.suma_netto
            vat_stawek["23"] = invoice.suma_vat

        wpis = RejestrSprzedazyWpis(
            numer_faktury=invoice.numer,
            data_sprzedazy=invoice.data_sprzedazy or invoice.data_wystawienia,
            nabywca_nazwa=invoice.nabywca.nazwa,
            nabywca_nip=invoice.nabywca.nip,
            netto_wg_stawek=netto_stawek,
            vat_wg_stawek=vat_stawek,
            suma_netto=invoice.suma_netto,
            suma_vat=invoice.suma_vat,
            suma_brutto=invoice.suma_brutto,
        )

        self.wpisy_sprzedazy.append(wpis)
        self.suma_sprzedaz_netto += wpis.suma_netto
        self.suma_sprzedaz_vat_nalezy += wpis.suma_vat
        self.suma_sprzedaz_brutto += wpis.suma_brutto

        for st, val in netto_stawek.items():
            self.sprzedaz_netto_wg_stawek[st] = self.sprzedaz_netto_wg_stawek.get(st, Decimal("0.00")) + val
        for st, val in vat_stawek.items():
            self.sprzedaz_vat_wg_stawek[st] = self.sprzedaz_vat_wg_stawek.get(st, Decimal("0.00")) + val

        return wpis

    def dodaj_fakture_zakupu(
        self,
        invoice: Invoice,
        forced_ratio: Optional[ProporcjaOdliczeniaVAT] = None,
        audit_report: Optional[Any] = None,
    ) -> RejestrZakupowWpis:
        """Księguje fakturę kosztową w rejestrze zakupów VAT z kwalifikacją odliczenia (w tym per-pozycja)."""
        if audit_report is not None:
            # Szczegółowa kwalifikacja per-pozycja z audytu kosztów
            vat_odliczenie = audit_report.kwalifikowany_vat
            vat_nieodliczony = invoice.suma_vat - vat_odliczenie
            netto_do_rejestru = audit_report.kwalifikowane_netto
            odrzucone_netto = audit_report.odrzucone_netto_prywatne
            odrzucony_vat = audit_report.odrzucony_vat_prywatny
            ratio = (
                ProporcjaOdliczeniaVAT.PELNE
                if vat_odliczenie == invoice.suma_vat
                else ProporcjaOdliczeniaVAT.SAMOCHOD_MIESZANY
            )
        else:
            # Klasyfikacja globalna faktury
            if forced_ratio is not None:
                ratio = forced_ratio
            elif invoice.pozycje:
                opis_zbiorczy = " ".join(p.opis for p in invoice.pozycje)
                ratio = classify_vat_deduction_ratio(opis_zbiorczy)
            else:
                ratio = ProporcjaOdliczeniaVAT.PELNE

            vat_odliczenie = (invoice.suma_vat * ratio.value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            vat_nieodliczony = invoice.suma_vat - vat_odliczenie
            netto_do_rejestru = invoice.suma_netto
            odrzucone_netto = Decimal("0.00")
            odrzucony_vat = Decimal("0.00")

        wpis = RejestrZakupowWpis(
            numer_faktury=invoice.numer,
            data_zakupu=invoice.data_sprzedazy or invoice.data_wystawienia,
            sprzedawca_nazwa=invoice.sprzedawca.nazwa,
            sprzedawca_nip=invoice.sprzedawca.nip,
            suma_netto=netto_do_rejestru,
            suma_vat_z_faktury=invoice.suma_vat,
            proporcja_odliczenia=ratio,
            vat_naliczony_do_odliczenia=vat_odliczenie,
            vat_nieodliczony=vat_nieodliczony,
            suma_brutto=invoice.suma_brutto,
            odrzucone_netto_prywatne=odrzucone_netto,
            odrzucony_vat_prywatny=odrzucony_vat,
        )

        self.wpisy_zakupow.append(wpis)
        self.suma_zakupy_netto += wpis.suma_netto
        self.suma_zakupy_vat_faktury += wpis.suma_vat_z_faktury
        self.suma_zakupy_vat_naliczony_odliczenie += wpis.vat_naliczony_do_odliczenia
        self.suma_zakupy_vat_nieodliczony += wpis.vat_nieodliczony
        self.suma_zakupy_odrzucone_netto_prywatne += wpis.odrzucone_netto_prywatne
        self.suma_zakupy_odrzucony_vat_prywatny += wpis.odrzucony_vat_prywatny
        self.suma_zakupy_brutto += wpis.suma_brutto

        return wpis

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "sprzedaz": {
                "liczba_faktur": len(self.wpisy_sprzedazy),
                "suma_netto": str(self.suma_sprzedaz_netto),
                "suma_vat_nalezy": str(self.suma_sprzedaz_vat_nalezy),
                "suma_brutto": str(self.suma_sprzedaz_brutto),
                "netto_wg_stawek": {k: str(v) for k, v in self.sprzedaz_netto_wg_stawek.items()},
                "vat_wg_stawek": {k: str(v) for k, v in self.sprzedaz_vat_wg_stawek.items()},
                "wpisy": [w.to_dict() for w in self.wpisy_sprzedazy],
            },
            "zakupy": {
                "liczba_faktur": len(self.wpisy_zakupow),
                "suma_netto": str(self.suma_zakupy_netto),
                "suma_vat_faktury": str(self.suma_zakupy_vat_faktury),
                "suma_vat_naliczony_odliczenie": str(self.suma_zakupy_vat_naliczony_odliczenie),
                "suma_vat_nieodliczony": str(self.suma_zakupy_vat_nieodliczony),
                "suma_odrzucone_netto_prywatne": str(self.suma_zakupy_odrzucone_netto_prywatne),
                "suma_odrzucony_vat_prywatny": str(self.suma_zakupy_odrzucony_vat_prywatny),
                "suma_brutto": str(self.suma_zakupy_brutto),
                "wpisy": [w.to_dict() for w in self.wpisy_zakupow],
            },
        }


@dataclass
class VATBalanceResult:
    """Rozliczenie bilansu VAT za dany miesiąc (odpowiednik deklaracji JPK_V7)."""

    rok: str
    miesiac: str
    vat_nalezy: Decimal
    vat_naliczony: Decimal
    roznica_vat: Decimal
    vat_do_zaplaty_zaokraglony: int
    vat_do_przeniesienia_na_kolejny_okres: Decimal
    termin_platnosci: str  # 25. dzień kolejnego miesiąca
    nadwyzka_z_poprzedniego_miesiaca: Decimal = Decimal("0.00")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "miesiac": self.miesiac,
            "vat_nalezy": str(self.vat_nalezy),
            "vat_nalezny": str(self.vat_nalezy),
            "vat_naliczony": str(self.vat_naliczony),
            "nadwyzka_z_poprzedniego_miesiaca": str(self.nadwyzka_z_poprzedniego_miesiaca),
            "roznica_vat": str(self.roznica_vat),
            "vat_do_zaplaty_zaokraglony": self.vat_do_zaplaty_zaokraglony,
            "vat_do_przeniesienia": str(self.vat_do_przeniesienia_na_kolejny_okres),
            "termin_platnosci": self.termin_platnosci,
        }


def calculate_vat_settlement(
    rejestr: RejestrVATMiesiaca, nadwyzka_z_poprzedniego_miesiaca: Decimal = Decimal("0.00")
) -> VATBalanceResult:
    """
    Oblicza ostateczny bilans VAT za dany miesiąc.

    1. VAT należny (ze sprzedaży) pomniejsza się o VAT naliczony do odliczenia (z zakupów).
    2. Uwzględnia się ewentualną nadwyżkę VAT z poprzedniego miesiąca.
    3. Jeśli bilans > 0: kwota podlega wpłacie do Urzędu Skarbowego (zaokrąglona do pełnych zł).
    4. Jeśli bilans < 0: kwota przenoszona jest na kolejny miesiąc (lub do zwrotu).
    """
    bezpieczna_nadwyzka = max(Decimal("0.00"), nadwyzka_z_poprzedniego_miesiaca)
    vat_nalezy = rejestr.suma_sprzedaz_vat_nalezy
    vat_naliczony = rejestr.suma_zakupy_vat_naliczony_odliczenie + bezpieczna_nadwyzka

    roznica = vat_nalezy - vat_naliczony

    if roznica > Decimal("0.00"):
        # Zaokrąglenie do pełnych złotych (Ordynacja Podatkowa)
        do_zaplaty = int(roznica.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        do_przeniesienia = Decimal("0.00")
    else:
        do_zaplaty = 0
        do_przeniesienia = abs(roznica)

    # Termin płatności VAT: 25. dzień następnego miesiąca
    m_int = int(rejestr.miesiac)
    rok_int = int(rejestr.rok)
    if m_int == 12:
        kolejny_rok = rok_int + 1
        kolejny_m = 1
    else:
        kolejny_rok = rok_int
        kolejny_m = m_int + 1
    termin_platnosci = f"{kolejny_rok:04d}-{kolejny_m:02d}-25"

    return VATBalanceResult(
        rok=rejestr.rok,
        miesiac=rejestr.miesiac,
        vat_nalezy=vat_nalezy,
        vat_naliczony=vat_naliczony,
        roznica_vat=roznica,
        vat_do_zaplaty_zaokraglony=do_zaplaty,
        vat_do_przeniesienia_na_kolejny_okres=do_przeniesienia,
        termin_platnosci=termin_platnosci,
        nadwyzka_z_poprzedniego_miesiaca=bezpieczna_nadwyzka,
    )
