"""
Moduł kwalifikacji pozycji faktur kosztowych i uczenia się reguł podatkowych.
Rozbija faktury zakupowe na pojedyncze pozycje i kwalifikuje:
- 100% VAT / KUP (wydatki firmowe)
- 50% VAT (samochód osobowy w trybie mieszanym)
- 0% VAT / wydatek osobisty (np. TV, usługi prywatne)
- do wyjaśnienia z przedsiębiorcą (human-in-the-loop)
Trwale zapisuje nauczone reguły w: firmy/{NIP}/reguly_kosztowe.json
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceItem
from src.core.io import atomic_write_json


class KwalifikacjaKosztu(str, Enum):
    FIRMOWY_100 = "FIRMOWY_100"  # 100% odliczenia VAT, 100% koszt uzyskania przychodu
    SAMOCHOD_50 = "SAMOCHOD_50"  # 50% odliczenia VAT, 75% koszt uzyskania przychodu
    PRYWATNY_0 = "PRYWATNY_0"  # 0% odliczenia VAT, wydatek osobisty (nie stanowi kosztu)
    DO_WYJASNIENIA = "DO_WYJASNIENIA"  # Agent ma wątpliwości, dopytuje użytkownika


# Wbudowane heurystyki
HEURYSTYKI_PRYWATNE = [
    r"\btv\b",
    r"telewizj",
    r"pakiet tv",
    r"vod",
    r"netflix",
    r"hbo",
    r"disney",
    r"playstation",
    r"xbox",
    r"gra komputerowa",
    r"kino",
    r"usług[iaęy]? medyczn.*rodzinn",
    r"pakiet.*medyczn.*rodzinn",
    r"pakiet.*rodzinn",
    r"zabawk",
    r"kosmetyk",
    r"fryzjer",
]

HEURYSTYKI_SAMOCHOD = [
    r"paliwo",
    r"benzyn",
    r"diesel",
    r"lpg",
    r"efecta",
    r"myjnia",
    r"wulkanizacj",
    r"opon",
    r"serwis auta",
    r"parking",
    r"autostrad",
]

HEURYSTYKI_FIRMOWE = [
    r"internet",
    r"\bświatłowód\b",
    r"\btelefon\b",
    r"telekomunikacyjn",
    r"komputer",
    r"kamera",
    r"klawiatur",
    r"monitor",
    r"serwer",
    r"hosting",
    r"chmur",
    r"cloud",
    r"księgow",
    r"doradztwo",
    r"biurow",
    r"kawa",
    r"espresso",
    r"nespresso",
]

HEURYSTYKI_NIEPEWNE = [
    r"^usługi inne$",
    r"^usługa inna$",
    r"^usługi dodatkowe$",
    r"^opłata$",
    r"^inne$",
    r"\blego\b",
    r"klocki",
    r"premia bankowa",
    r"\bpremia\b",
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
            "reguly_kontrahentow": {nip: [r.to_dict() for r in regs] for nip, regs in self.reguly_kontrahentow.items()},
            "reguly_globalne": [r.to_dict() for r in self.reguly_globalne],
        }
        return atomic_write_json(path, data, indent=2, ensure_ascii=False)

    def dodaj_regule(
        self,
        profile: CompanyProfile,
        wzorzec: str,
        kwalifikacja: KwalifikacjaKosztu,
        uzasadnienie: str,
        nip_kontrahenta: Optional[str] = None,
    ):
        wzorzec_clean = wzorzec.strip().lower()
        wz_norm = CostClassifier.normalize_desc(wzorzec_clean)
        regula = RegulaPozycji(wzorzec=wzorzec_clean, kwalifikacja=kwalifikacja, uzasadnienie=uzasadnienie)
        if nip_kontrahenta:
            nip_clean = re.sub(r"[^0-9]", "", nip_kontrahenta)
            regs = self.reguly_kontrahentow.setdefault(nip_clean, [])
            # Usuń wcześniejsze reguły o tym samym wzorcu, aby nowa decyzja użytkownika miała natychmiastowy priorytet
            self.reguly_kontrahentow[nip_clean] = [
                r for r in regs if CostClassifier.normalize_desc(r.wzorzec) != wz_norm
            ]
            self.reguly_kontrahentow[nip_clean].insert(0, regula)
        else:
            self.reguly_globalne = [
                r for r in self.reguly_globalne if CostClassifier.normalize_desc(r.wzorzec) != wz_norm
            ]
            self.reguly_globalne.insert(0, regula)
        self.save(profile)

    def usun_regule(self, profile: CompanyProfile, wzorzec: str, nip_kontrahenta: Optional[str] = None) -> bool:
        wzorzec_clean = wzorzec.strip().lower()
        wz_norm = CostClassifier.normalize_desc(wzorzec_clean)
        zmieniono = False

        if nip_kontrahenta:
            nip_clean = re.sub(r"[^0-9]", "", nip_kontrahenta)
            if nip_clean in self.reguly_kontrahentow:
                pocz_len = len(self.reguly_kontrahentow[nip_clean])
                self.reguly_kontrahentow[nip_clean] = [
                    r
                    for r in self.reguly_kontrahentow[nip_clean]
                    if CostClassifier.normalize_desc(r.wzorzec) != wz_norm
                ]
                if len(self.reguly_kontrahentow[nip_clean]) < pocz_len:
                    zmieniono = True
                if not self.reguly_kontrahentow[nip_clean]:
                    del self.reguly_kontrahentow[nip_clean]
        else:
            pocz_len = len(self.reguly_globalne)
            self.reguly_globalne = [
                r for r in self.reguly_globalne if CostClassifier.normalize_desc(r.wzorzec) != wz_norm
            ]
            if len(self.reguly_globalne) < pocz_len:
                zmieniono = True

        if zmieniono:
            self.save(profile)
        return zmieniono

    def pobierz_wszystkie_reguly(self) -> List[Dict[str, Any]]:
        wyniki: List[Dict[str, Any]] = []
        labels = {
            KwalifikacjaKosztu.FIRMOWY_100: "✅ 100% Firmowy",
            KwalifikacjaKosztu.SAMOCHOD_50: "🚗 50% Samochód",
            KwalifikacjaKosztu.PRYWATNY_0: "⛔ 0% Prywatny",
            KwalifikacjaKosztu.DO_WYJASNIENIA: "⚠️ Do wyjaśnienia",
        }
        # 1. Reguły przypisane do kontrahentów
        for nip, reguly in self.reguly_kontrahentow.items():
            for r in reguly:
                wyniki.append(
                    {
                        "typ": "KONTRAHENT",
                        "nip_kontrahenta": nip,
                        "wzorzec": r.wzorzec,
                        "kwalifikacja": r.kwalifikacja.value,
                        "kwalifikacja_label": labels.get(r.kwalifikacja, r.kwalifikacja.value),
                        "uzasadnienie": r.uzasadnienie,
                        "data_utworzenia": r.data_utworzenia,
                    }
                )
        # 2. Reguły globalne
        for r in self.reguly_globalne:
            wyniki.append(
                {
                    "typ": "GLOBALNA",
                    "nip_kontrahenta": "",
                    "wzorzec": r.wzorzec,
                    "kwalifikacja": r.kwalifikacja.value,
                    "kwalifikacja_label": labels.get(r.kwalifikacja, r.kwalifikacja.value),
                    "uzasadnienie": r.uzasadnienie,
                    "data_utworzenia": r.data_utworzenia,
                }
            )
        return wyniki


class ReczneKwalifikacjeService:
    """
    Zarządza miesięcznymi decyzjami przedsiębiorcy (manual overrides) w widoku przeglądu.
    Wybór w selektorze okresowym zapisuje decyzję dla konkretnej faktury / pozycji w danym miesiącu,
    nie modyfikując ogólnych reguł firmy w reguly_kosztowe.json.
    """

    @classmethod
    def sciezka_pliku(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        m_pad = str(miesiac).zfill(2)
        return profile.katalog_firmy / "rozliczenia" / str(rok) / m_pad / "reczne_kwalifikacje.json"

    @classmethod
    def load_overrides(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Dict[str, Dict[str, Any]]:
        path = cls.sciezka_pliku(profile, rok, miesiac)
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def save_override(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        numer_faktury: str,
        kwalifikacja: KwalifikacjaKosztu,
        opis_pozycji: Optional[str] = None,
    ) -> Path:
        path = cls.sciezka_pliku(profile, rok, miesiac)
        path.parent.mkdir(parents=True, exist_ok=True)
        overrides = cls.load_overrides(profile, rok, miesiac)

        num_clean = numer_faktury.strip()
        if opis_pozycji and opis_pozycji.strip():
            klucz = f"{num_clean}::{CostClassifier.normalize_desc(opis_pozycji.strip())}"
        else:
            klucz = num_clean

        overrides[klucz] = {
            "kwalifikacja": kwalifikacja.value,
            "numer_faktury": num_clean,
            "opis_pozycji": opis_pozycji.strip() if opis_pozycji else None,
            "data_zapisu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        return atomic_write_json(path, overrides, indent=2, ensure_ascii=False)

    @classmethod
    def save_bulk_overrides(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        numer_faktury: str,
        kwalifikacja: KwalifikacjaKosztu,
        opisy_pozycji: List[str],
    ) -> Path:
        """
        Zapisuje zbiorczą decyzję ręczną dla wszystkich pozycji wskazanej faktury w jednym zapisie.
        """
        path = cls.sciezka_pliku(profile, rok, miesiac)
        path.parent.mkdir(parents=True, exist_ok=True)
        overrides = cls.load_overrides(profile, rok, miesiac)

        num_clean = numer_faktury.strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Zapis dla samej faktury (agregat)
        overrides[num_clean] = {
            "kwalifikacja": kwalifikacja.value,
            "numer_faktury": num_clean,
            "opis_pozycji": None,
            "data_zapisu": now_str,
        }

        # Zapis dla każdej pozycji faktury
        for opis in opisy_pozycji:
            if opis and opis.strip():
                klucz = f"{num_clean}::{CostClassifier.normalize_desc(opis.strip())}"
                overrides[klucz] = {
                    "kwalifikacja": kwalifikacja.value,
                    "numer_faktury": num_clean,
                    "opis_pozycji": opis.strip(),
                    "data_zapisu": now_str,
                }

        return atomic_write_json(path, overrides, indent=2, ensure_ascii=False)

    @classmethod
    def clear_override(
        cls, profile: CompanyProfile, rok: str, miesiac: str, numer_faktury: str, opis_pozycji: Optional[str] = None
    ) -> bool:
        path = cls.sciezka_pliku(profile, rok, miesiac)
        if not path.exists():
            return False
        overrides = cls.load_overrides(profile, rok, miesiac)
        num_clean = numer_faktury.strip()
        if opis_pozycji and opis_pozycji.strip():
            klucz = f"{num_clean}::{CostClassifier.normalize_desc(opis_pozycji.strip())}"
        else:
            klucz = num_clean

        if klucz in overrides:
            del overrides[klucz]
            atomic_write_json(path, overrides, indent=2, ensure_ascii=False)
            return True
        return False


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

    @staticmethod
    def normalize_desc(text: str) -> str:
        """Ujednolica myślniki, pauzy, białe znaki i kropki na końcu tekstu."""
        if not text:
            return ""
        t = text.strip().lower()
        t = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\-]+", "-", t)
        t = re.sub(r"\s+", " ", t)
        return t.rstrip(".")

    @classmethod
    def _find_best_matching_rule(cls, rules: List[RegulaPozycji], desc: str) -> Optional[RegulaPozycji]:
        """
        Wybiera najlepiej dopasowaną regułę kosztową według ściśle zdefiniowanej hierarchii:
        1. Dokładne dopasowanie (Exact Match - najwyższy priorytet).
        2. Najdłuższe dopasowanie podciągu (Longest Substring Match - bardziej specyficzny wzorzec wygrywa).
        3. Wildcard ('*' lub pusty wzorzec).
        """
        if not rules:
            return None
        d_norm = cls.normalize_desc(desc)
        if not d_norm:
            return None

        # Poziom 1: Dokładne dopasowanie (Exact Match)
        for r in rules:
            w_norm = cls.normalize_desc(r.wzorzec)
            if w_norm and w_norm == d_norm:
                return r

        # Poziom 2: Dopasowanie podciągu (Longest Substring Match)
        # Np. "usługi telekomunikacyjne – tv" ma wyższy priorytet niż ogólne "usługi telekomunikacyjne"
        candidates = []
        for idx, r in enumerate(rules):
            w_norm = cls.normalize_desc(r.wzorzec)
            if w_norm and w_norm != "*" and w_norm in d_norm:
                candidates.append((len(w_norm), -idx, r))

        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][2]

        # Poziom 3: Wildcard ('*' lub pusty)
        for r in rules:
            w_norm = cls.normalize_desc(r.wzorzec)
            if w_norm == "*" or not w_norm:
                return r

        return None

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
        clean_seller = re.sub(r"[^0-9]", "", seller_nip)
        if clean_seller in reguly_firmy.reguly_kontrahentow:
            matched_reg = cls._find_best_matching_rule(reguly_firmy.reguly_kontrahentow[clean_seller], item.opis)
            if matched_reg:
                return cls._build_result(item, matched_reg.kwalifikacja, matched_reg.uzasadnienie, "REGULA_KONTRAHENTA")

        # 2. Sprawdź reguły globalne firmy
        matched_reg = cls._find_best_matching_rule(reguly_firmy.reguly_globalne, item.opis)
        if matched_reg:
            return cls._build_result(item, matched_reg.kwalifikacja, matched_reg.uzasadnienie, "REGULA_GLOBALNA")

        # 3. Sprawdź heurystyki wbudowane
        # 3a. Niepewne ogólniki (wymagają pytania do użytkownika)
        for pattern in HEURYSTYKI_NIEPEWNE:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.DO_WYJASNIENIA,
                    "Zbyt ogólny opis pozycji – wymaga potwierdzenia przez przedsiębiorcę",
                    "DO_WYJASNIENIA",
                )

        # 3b. Prywatne / osobiste
        for pattern in HEURYSTYKI_PRYWATNE:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.PRYWATNY_0,
                    f"Wydatek o charakterze osobistym (wzorzec '{pattern}') – nie stanowi kosztu firmy",
                    "HEURYSTYKA",
                )

        # 3c. Samochód osobowy (tryb mieszany 50% VAT)
        for pattern in HEURYSTYKI_SAMOCHOD:
            if re.search(pattern, desc_clean):
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.SAMOCHOD_50,
                    "Eksploatacja pojazdu osobowego w trybie mieszanym (art. 86a ustawy o VAT)",
                    "HEURYSTYKA",
                )

        # 3d. Firmowe
        for pattern in HEURYSTYKI_FIRMOWE:
            if re.search(pattern, desc_clean):
                pkd_info = f" (zbieżne z PKD firmy: {', '.join(kody_pkd[:3])})" if kody_pkd else ""
                return cls._build_result(
                    item,
                    KwalifikacjaKosztu.FIRMOWY_100,
                    f"Wydatek firmowy związany z prowadzoną działalnością{pkd_info}",
                    "HEURYSTYKA",
                )

        # Domyślnie – jeśli nic nie pasuje: firmowy 100% z ostrożną notatką
        pkd_domyslne = f" (profil PKD: {', '.join(kody_pkd[:2])})" if kody_pkd else ""
        return cls._build_result(
            item, KwalifikacjaKosztu.FIRMOWY_100, f"Standardowy wydatek bieżący firmy{pkd_domyslne}", "DOMYSLNA"
        )

    @classmethod
    def _build_result(
        cls, item: InvoiceItem, kwalifikacja: KwalifikacjaKosztu, uzasadnienie: str, zrodlo: str
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
    reczne_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> InvoiceTaxAuditReport:
    """
    Przeprowadza szczegółowy audyt pozycji faktury kosztowej.
    Ręczne decyzje przedsiębiorcy z danego miesiąca (reczne_overrides) mają bezwzględny
    priorytet nad regułami ogólnymi i heurystykami.
    """
    pozycje_wyniki: List[PozycjaKwalifikacjaResult] = []
    pytania: List[str] = []
    overrides = reczne_overrides or {}
    inv_num_clean = invoice.numer.strip()

    if invoice.pozycje:
        for p in invoice.pozycje:
            key_pos = f"{inv_num_clean}::{CostClassifier.normalize_desc(p.opis)}"
            ov = overrides.get(key_pos)
            if not ov:
                ov = overrides.get(inv_num_clean)

            if ov:
                target_kwal = KwalifikacjaKosztu(ov["kwalifikacja"])
                res = CostClassifier._build_result(
                    p, target_kwal, "Ręczna decyzja przedsiębiorcy w bieżącym okresie", "DECYZJA_RECZNA"
                )
            else:
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
            wartosc_brutto=invoice.suma_brutto,
        )
        ov = overrides.get(inv_num_clean)
        if ov:
            target_kwal = KwalifikacjaKosztu(ov["kwalifikacja"])
            res = CostClassifier._build_result(
                dummy_item, target_kwal, "Ręczna decyzja przedsiębiorcy w bieżącym okresie", "DECYZJA_RECZNA"
            )
        else:
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
            odrzucone_netto = sum(
                (p.wartosc_netto for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0),
                Decimal("0.00"),
            )
            odrzucony_vat = sum(
                (p.kwota_vat for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0),
                Decimal("0.00"),
            )
    else:
        kwalifikowane_netto = sum((p.netto_do_kup for p in pozycje_wyniki), Decimal("0.00"))
        kwalifikowany_vat = sum((p.vat_do_odliczenia for p in pozycje_wyniki), Decimal("0.00"))
        odrzucone_netto = sum(
            (p.wartosc_netto for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0),
            Decimal("0.00"),
        )
        odrzucony_vat = sum(
            (p.kwota_vat for p in pozycje_wyniki if p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0), Decimal("0.00")
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
