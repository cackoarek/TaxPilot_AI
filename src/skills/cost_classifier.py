"""
Moduł kwalifikacji pozycji faktur kosztowych i uczenia się reguł podatkowych.
Rozbija faktury zakupowe na pojedyncze pozycje i kwalifikuje:
- 100% VAT / KUP (wydatki firmowe)
- 50% VAT (samochód osobowy w trybie mieszanym)
- 0% VAT / wydatek osobisty (np. TV, usługi prywatne)
- do wyjaśnienia z przedsiębiorcą (human-in-the-loop)
Trwale zapisuje nauczone reguły w: firmy/{NIP}/reguly_kosztowe.json
"""

from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import json
import re
from datetime import datetime

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceItem


class KwalifikacjaKosztu(str, Enum):
    FIRMOWY_100 = "FIRMOWY_100"          # 100% odliczenia VAT, 100% koszt uzyskania przychodu
    SAMOCHOD_50 = "SAMOCHOD_50"          # 50% odliczenia VAT, 75% koszt uzyskania przychodu
    PRYWATNY_0 = "PRYWATNY_0"            # 0% odliczenia VAT, wydatek osobisty (nie stanowi kosztu)
    DO_WYJASNIENIA = "DO_WYJASNIENIA"   # Agent ma wątpliwości, dopytuje użytkownika


# Wbudowane heurystyki
HEURYSTYKI_PRYWATNE = [
    r"\btv\b", r"telewizj", r"pakiet tv", r"vod", r"netflix", r"hbo", r"disney",
    r"playstation", r"xbox", r"gra komputerowa", r"kino",
    r"usług[iaęy]? medyczn.*rodzinn", r"pakiet.*medyczn.*rodzinn", r"pakiet.*rodzinn",
    r"zabawk", r"kosmetyk", r"fryzjer"
]

HEURYSTYKI_SAMOCHOD = [
    r"paliwo", r"benzyn", r"diesel", r"lpg", r"efecta", r"myjnia", r"wulkanizacj",
    r"opon", r"serwis auta", r"parking", r"autostrad"
]

HEURYSTYKI_FIRMOWE = [
    r"internet", r"\bświatłowód\b", r"\btelefon\b", r"telekomunikacyjn", r"komputer",
    r"kamera", r"klawiatur", r"monitor", r"serwer", r"hosting", r"chmur", r"cloud",
    r"księgow", r"doradztwo", r"biurow", r"kawa", r"espresso", r"nespresso"
]

HEURYSTYKI_NIEPEWNE = [
    r"^usługi inne$", r"^usługa inna$", r"^usługi dodatkowe$", r"^opłata$", r"^inne$",
    r"\blego\b", r"klocki", r"premia bankowa", r"\bpremia\b"
]


@dataclass
class RegulaPozycji:
    wzorzec: str
    kwalifikacja: KwalifikacjaKosztu
    uzasadnienie: str
    data_utworzenia: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wzorzec": self.wzorzec,
            "kwalifikacja": self.kwalifikacja.value,
            "uzasadnienie": self.uzasadnienie,
            "data_utworzenia": self.data_utworzenia,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegulaPozycji":
        return cls(
            wzorzec=data["wzorzec"],
            kwalifikacja=KwalifikacjaKosztu(data["kwalifikacja"]),
            uzasadnienie=data.get("uzasadnienie", ""),
            data_utworzenia=data.get("data_utworzenia", ""),
        )


@dataclass
class RegulyKosztoweFirmy:
    nip_firmy: str
    reguly_kontrahentow: Dict[str, List[RegulaPozycji]] = field(default_factory=dict)
    reguly_globalne: List[RegulaPozycji] = field(default_factory=list)

    @classmethod
    def sciezka_pliku(cls, profile: CompanyProfile) -> Path:
        return profile.katalog_firmy / "reguly_kosztowe.json"

    @classmethod
    def load(cls, profile: CompanyProfile) -> "RegulyKosztoweFirmy":
        path = cls.sciezka_pliku(profile)
        if not path.exists():
            return cls(nip_firmy=profile.nip)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            kontrahenci = {}
            for nip, regs in data.get("reguly_kontrahentow", {}).items():
                kontrahenci[nip] = [RegulaPozycji.from_dict(r) for r in regs]
            globalne = [RegulaPozycji.from_dict(r) for r in data.get("reguly_globalne", [])]
            return cls(nip_firmy=profile.nip, reguly_kontrahentow=kontrahenci, reguly_globalne=globalne)
        except Exception:
            return cls(nip_firmy=profile.nip)

    def save(self, profile: CompanyProfile) -> Path:
        path = self.sciezka_pliku(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nip_firmy": self.nip_firmy,
            "reguly_kontrahentow": {
                nip: [r.to_dict() for r in regs]
                for nip, regs in self.reguly_kontrahentow.items()
            },
            "reguly_globalne": [r.to_dict() for r in self.reguly_globalne],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path

    def dodaj_regule(
        self,
        profile: CompanyProfile,
        wzorzec: str,
        kwalifikacja: KwalifikacjaKosztu,
        uzasadnienie: str,
        nip_kontrahenta: Optional[str] = None
    ):
        regula = RegulaPozycji(wzorzec=wzorzec.lower(), kwalifikacja=kwalifikacja, uzasadnienie=uzasadnienie)
        if nip_kontrahenta:
            self.reguly_kontrahentow.setdefault(nip_kontrahenta, []).append(regula)
        else:
            self.reguly_globalne.append(regula)
        self.save(profile)


@dataclass
class PozycjaKwalifikacjaResult:
    opis: str
    wartosc_netto: Decimal
    kwota_vat: Decimal
    stawka_vat: str
    wartosc_brutto: Decimal
    kwalifikacja: KwalifikacjaKosztu
    vat_odliczenie_procent: Decimal
    vat_do_odliczenia: Decimal
    netto_do_kup: Decimal
    uzasadnienie: str
    zrodlo_decyzji: str  # "REGULA_KONTRAHENTA" | "REGULA_GLOBALNA" | "HEURYSTYKA" | "DO_WYJASNIENIA"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opis": self.opis,
            "wartosc_netto": str(self.wartosc_netto),
            "kwota_vat": str(self.kwota_vat),
            "stawka_vat": self.stawka_vat,
            "wartosc_brutto": str(self.wartosc_brutto),
            "kwalifikacja": self.kwalifikacja.value,
            "vat_odliczenie_procent": str(self.vat_odliczenie_procent),
            "vat_do_odliczenia": str(self.vat_do_odliczenia),
            "netto_do_kup": str(self.netto_do_kup),
            "uzasadnienie": self.uzasadnienie,
            "zrodlo_decyzji": self.zrodlo_decyzji,
        }


class CostClassifier:
    """
    Ekspert klasyfikacji kosztów podatkowych.
    """

    @classmethod
    def classify_item(
        cls,
        item: InvoiceItem,
        seller_nip: str,
        reguly_firmy: RegulyKosztoweFirmy,
        kody_pkd: Optional[List[str]] = None,
    ) -> PozycjaKwalifikacjaResult:
        desc_clean = item.opis.strip().lower()

        # 1. Sprawdź specyficzne reguły dla danego kontrahenta
        if seller_nip in reguly_firmy.reguly_kontrahentow:
            for reg in reguly_firmy.reguly_kontrahentow[seller_nip]:
                if reg.wzorzec in desc_clean:
                    return cls._build_result(item, reg.kwalifikacja, reg.uzasadnienie, "REGULA_KONTRAHENTA")

        # 2. Sprawdź reguły globalne firmy
        for reg in reguly_firmy.reguly_globalne:
            if reg.wzorzec in desc_clean:
                return cls._build_result(item, reg.kwalifikacja, reg.uzasadnienie, "REGULA_GLOBALNA")

        # 3. Sprawdź heurystyki wbudowane
        # 3a. Niepewne ogólniki (wymagają pytania do użytkownika)
        for pattern in HEURYSTYKI_NIEPEWNE:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.DO_WYJASNIENIA,
                    "Zbyt ogólny opis pozycji – wymaga potwierdzenia przez przedsiębiorcę",
                    "DO_WYJASNIENIA"
                )

        # 3b. Prywatne / osobiste
        for pattern in HEURYSTYKI_PRYWATNE:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.PRYWATNY_0,
                    f"Wydatek o charakterze osobistym (wzorzec '{pattern}') – nie stanowi kosztu firmy",
                    "HEURYSTYKA"
                )

        # 3c. Samochód osobowy (tryb mieszany 50% VAT)
        for pattern in HEURYSTYKI_SAMOCHOD:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.SAMOCHOD_50,
                    "Eksploatacja pojazdu osobowego w trybie mieszanym (art. 86a ustawy o VAT)",
                    "HEURYSTYKA"
                )

        # 3d. Firmowe
        for pattern in HEURYSTYKI_FIRMOWE:
            if re.search(pattern, desc_clean):
                pkd_info = f" (zbieżne z PKD firmy: {', '.join(kody_pkd[:3])})" if kody_pkd else ""
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.FIRMOWY_100,
                    f"Wydatek firmowy związany z prowadzoną działalnością{pkd_info}",
                    "HEURYSTYKA"
                )

        # Domyślnie – jeśli nic nie pasuje: firmowy 100% z ostrożną notatką
        pkd_domyslne = f" (profil PKD: {', '.join(kody_pkd[:2])})" if kody_pkd else ""
        return cls._build_result(
            item,
            KwalifikacjaKosztu.FIRMOWY_100,
            f"Standardowy wydatek bieżący firmy{pkd_domyslne}",
            "DOMYSLNA"
        )

    @classmethod
    def _build_result(
        cls,
        item: InvoiceItem,
        kwalifikacja: KwalifikacjaKosztu,
        uzasadnienie: str,
        zrodlo: str
    ) -> PozycjaKwalifikacjaResult:
        if kwalifikacja == KwalifikacjaKosztu.FIRMOWY_100:
            ratio_vat = Decimal("1.00")
            vat_odliczenie = item.kwota_vat
            netto_kup = item.wartosc_netto
        elif kwalifikacja == KwalifikacjaKosztu.SAMOCHOD_50:
            ratio_vat = Decimal("0.50")
            vat_odliczenie = (item.kwota_vat * ratio_vat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            netto_kup = item.wartosc_netto
        elif kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0:
            ratio_vat = Decimal("0.00")
            vat_odliczenie = Decimal("0.00")
            netto_kup = Decimal("0.00")
        else:  # DO_WYJASNIENIA – tymczasowo ostrożnie 0 zł do czasu decyzji
            ratio_vat = Decimal("0.00")
            vat_odliczenie = Decimal("0.00")
            netto_kup = Decimal("0.00")

        return PozycjaKwalifikacjaResult(
            opis=item.opis,
            wartosc_netto=item.wartosc_netto,
            kwota_vat=item.kwota_vat,
            stawka_vat=item.stawka_vat,
            wartosc_brutto=item.wartosc_brutto,
            kwalifikacja=kwalifikacja,
            vat_odliczenie_procent=ratio_vat,
            vat_do_odliczenia=vat_odliczenie,
            netto_do_kup=netto_kup,
            uzasadnienie=uzasadnienie,
            zrodlo_decyzji=zrodlo,
        )


@dataclass
class InvoiceTaxAuditReport:
    """Kompletny raport audytu podatkowego faktury kosztowej."""
    numer_faktury: str
    data: str
    sprzedawca_nazwa: str
    sprzedawca_nip: str
    suma_faktury_netto: Decimal
    suma_faktury_vat: Decimal
    suma_faktury_brutto: Decimal
    kwalifikowane_netto: Decimal
    kwalifikowany_vat: Decimal
    odrzucone_netto_prywatne: Decimal
    odrzucony_vat_prywatny: Decimal
    pozycje_wyniki: List[PozycjaKwalifikacjaResult]
    wymaga_wyjasnienia: bool = False
    pytania_do_uzytkownika: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "numer_faktury": self.numer_faktury,
            "data": self.data,
            "sprzedawca_nazwa": self.sprzedawca_nazwa,
            "sprzedawca_nip": self.sprzedawca_nip,
            "suma_faktury_netto": str(self.suma_faktury_netto),
            "suma_faktury_vat": str(self.suma_faktury_vat),
            "suma_faktury_brutto": str(self.suma_faktury_brutto),
            "kwalifikowane_netto": str(self.kwalifikowane_netto),
            "kwalifikowany_vat": str(self.kwalifikowany_vat),
            "odrzucone_netto_prywatne": str(self.odrzucone_netto_prywatne),
            "odrzucony_vat_prywatny": str(self.odrzucony_vat_prywatny),
            "wymaga_wyjasnienia": self.wymaga_wyjasnienia,
            "pytania_do_uzytkownika": self.pytania_do_uzytkownika,
            "pozycje": [p.to_dict() for p in self.pozycje_wyniki],
        }


def audit_invoice_expense(
    invoice: Invoice,
    reguly_firmy: RegulyKosztoweFirmy,
    kody_pkd: Optional[List[str]] = None,
) -> InvoiceTaxAuditReport:
    """
    Przeprowadza szczegółowy audyt pozycji faktury kosztowej.
    """
    pozycje_wyniki: List[PozycjaKwalifikacjaResult] = []
    pytania: List[str] = []

    if invoice.pozycje:
        for p in invoice.pozycje:
            res = CostClassifier.classify_item(p, invoice.sprzedawca.nip, reguly_firmy, kody_pkd=kody_pkd)
            pozycje_wyniki.append(res)
            if res.kwalifikacja == KwalifikacjaKosztu.DO_WYJASNIENIA:
                pytania.append(
                    f"Faktura {invoice.numer} ({invoice.sprzedawca.nazwa}): pozycja '{p.opis}' ({p.wartosc_netto} zł netto) – czy zaliczyć do kosztów firmy, czy jest to wydatek prywatny?"
                )
    else:
        # Faktura bez rozbitych pozycji – klasyfikujemy po nazwie sprzedawcy lub opisie faktury
        dummy_item = InvoiceItem(
            opis=invoice.numer,
            wartosc_netto=invoice.suma_netto,
            kwota_vat=invoice.suma_vat,
            wartosc_brutto=invoice.suma_brutto
        )
        res = CostClassifier.classify_item(dummy_item, invoice.sprzedawca.nip, reguly_firmy, kody_pkd=kody_pkd)
        pozycje_wyniki.append(res)

    # Weryfikacja spójności kwalifikacji pozycji:
    # Jeśli wszystkie pozycje mają taką samą kwalifikację, kwoty uzgadniamy z nagłówkiem faktury,
    # aby uniknąć groszowych rozbieżności zaokrągleń cząstkowych pozycji (art. 106e / art. 86 ustawy o VAT).
    unikalne_kwalifikacje = set(p.kwalifikacja for p in pozycje_wyniki)
    if len(unikalne_kwalifikacje) == 1:
        jedyna = next(iter(unikalne_kwalifikacje))
        if jedyna == KwalifikacjaKosztu.FIRMOWY_100:
            kwalifikowane_netto = invoice.suma_netto
            kwalifikowany_vat = invoice.suma_vat
            odrzucone_netto = Decimal("0.00")
            odrzucony_vat = Decimal("0.00")
        elif jedyna == KwalifikacjaKosztu.SAMOCHOD_50:
            kwalifikowane_netto = invoice.suma_netto
            kwalifikowany_vat = (invoice.suma_vat * Decimal("0.50")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            odrzucone_netto = Decimal("0.00")
            odrzucony_vat = Decimal("0.00")
        elif jedyna == KwalifikacjaKosztu.PRYWATNY_0:
            kwalifikowane_netto = Decimal("0.00")
            kwalifikowany_vat = Decimal("0.00")
            odrzucone_netto = invoice.suma_netto
            odrzucony_vat = invoice.suma_vat
        else:
            kwalifikowane_netto = sum((p.netto_do_kup for p in pozycje_wyniki), Decimal("0.00"))
            kwalifikowany_vat = sum((p.vat_do_odliczenia for p in pozycje_wyniki), Decimal("0.00"))
            odrzucone_netto = sum((p.wartosc_netto for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0), Decimal("0.00"))
            odrzucony_vat = sum((p.kwota_vat for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0), Decimal("0.00"))
    else:
        kwalifikowane_netto = sum((p.netto_do_kup for p in pozycje_wyniki), Decimal("0.00"))
        kwalifikowany_vat = sum((p.vat_do_odliczenia for p in pozycje_wyniki), Decimal("0.00"))
        odrzucone_netto = sum(
            (p.wartosc_netto for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0),
            Decimal("0.00")
        )
        odrzucony_vat = sum(
            (p.kwota_vat for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0),
            Decimal("0.00")
        )

    return InvoiceTaxAuditReport(
        numer_faktury=invoice.numer,
        data=invoice.data_wystawienia,
        sprzedawca_nazwa=invoice.sprzedawca.nazwa,
        sprzedawca_nip=invoice.sprzedawca.nip,
        suma_faktury_netto=invoice.suma_netto,
        suma_faktury_vat=invoice.suma_vat,
        suma_faktury_brutto=invoice.suma_brutto,
        kwalifikowane_netto=kwalifikowane_netto,
        kwalifikowany_vat=kwalifikowany_vat,
        odrzucone_netto_prywatne=odrzucone_netto,
        odrzucony_vat_prywatny=odrzucony_vat,
        pozycje_wyniki=pozycje_wyniki,
        wymaga_wyjasnienia=bool(pytania),
        pytania_do_uzytkownika=pytania,
    )

