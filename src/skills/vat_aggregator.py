"""
Moduł agregacji odliczeń VAT wg kategorii podatkowych i branżowych.
Deterministyczne obliczenia w oparciu o typ Decimal zgodnie z zasadami TaxPilot AI.
"""

import glob
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class CategoryAggregation:
    kategoria: str
    opis: str
    proporcja_vat: str  # "100%", "50%", "0%" lub "MIX"
    liczba_faktur: int = 0
    liczba_pozycji: int = 0
    suma_netto: Decimal = field(default_factory=lambda: Decimal("0.00"))
    suma_vat_z_faktur: Decimal = field(default_factory=lambda: Decimal("0.00"))
    suma_vat_odliczony: Decimal = field(default_factory=lambda: Decimal("0.00"))
    suma_vat_nieodliczony: Decimal = field(default_factory=lambda: Decimal("0.00"))
    udzial_w_odliczeniu_procent: Decimal = field(default_factory=lambda: Decimal("0.00"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kategoria": self.kategoria,
            "opis": self.opis,
            "proporcja_vat": self.proporcja_vat,
            "liczba_faktur": self.liczba_faktur,
            "liczba_pozycji": self.liczba_pozycji,
            "suma_netto": str(self.suma_netto),
            "suma_vat_z_faktur": str(self.suma_vat_z_faktur),
            "suma_vat_odliczony": str(self.suma_vat_odliczony),
            "suma_vat_nieodliczony": str(self.suma_vat_nieodliczony),
            "udzial_w_odliczeniu_procent": str(self.udzial_w_odliczeniu_procent),
        }


@dataclass
class VATAggregationReport:
    nip: str
    firma: str
    rok: str
    zamkniete_miesiace: List[str]
    laczny_vat_odliczony: Decimal
    laczny_vat_nalezy: Decimal
    laczny_vat_zaplacony_us: Decimal
    laczny_vat_z_faktur_kosztowych: Decimal
    laczny_vat_nieodliczony: Decimal
    kategorie_podatkowe: Dict[str, CategoryAggregation]
    kategorie_biznesowe: Dict[str, CategoryAggregation]
    zestawienie_miesieczne: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nip": self.nip,
            "firma": self.firma,
            "rok": self.rok,
            "zamkniete_miesiace": self.zamkniete_miesiace,
            "laczny_vat_odliczony": str(self.laczny_vat_odliczony),
            "laczny_vat_nalezy": str(self.laczny_vat_nalezy),
            "laczny_vat_zaplacony_us": str(self.laczny_vat_zaplacony_us),
            "laczny_vat_z_faktur_kosztowych": str(self.laczny_vat_z_faktur_kosztowych),
            "laczny_vat_nieodliczony": str(self.laczny_vat_nieodliczony),
            "kategorie_podatkowe": {k: v.to_dict() for k, v in self.kategorie_podatkowe.items()},
            "kategorie_biznesowe": {k: v.to_dict() for k, v in self.kategorie_biznesowe.items()},
            "zestawienie_miesieczne": self.zestawienie_miesieczne,
        }

    def to_markdown(self) -> str:
        lines = []
        lines.append(f"# Raport Agregacji Odliczeń VAT – {self.rok}")
        lines.append(f"**Firma:** {self.firma} (NIP: {self.nip})  ")
        lines.append(f"**Okres rozliczony:** {', '.join(self.zamkniete_miesiace)} / {self.rok}  ")
        lines.append(f"**Łączny odliczony VAT:** **{self.laczny_vat_odliczony:,.2f} zł**  \n")

        lines.append("## 1. Zestawienie wg Zasad Prawa Podatkowego")
        lines.append(
            "| Kategoria podatkowa | Zasada | Netto | VAT z faktur | VAT odliczony | VAT nieodliczony | Udział |"
        )
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|")
        for kat in self.kategorie_podatkowe.values():
            lines.append(
                f"| **{kat.opis}** | {kat.proporcja_vat} | {kat.suma_netto:,.2f} zł | {kat.suma_vat_z_faktur:,.2f} zł | "
                f"**{kat.suma_vat_odliczony:,.2f} zł** | {kat.suma_vat_nieodliczony:,.2f} zł | {kat.udzial_w_odliczeniu_procent:.1f}% |"
            )

        lines.append("\n## 2. Zestawienie wg Kategorii Biznesowych / Branżowych")
        lines.append("| Kategoria biznesowa | Liczba FV | Wartość netto | VAT odliczony | Udział |")
        lines.append("|:---|:---:|:---:|:---:|:---:|")
        for kat in sorted(self.kategorie_biznesowe.values(), key=lambda x: x.suma_vat_odliczony, reverse=True):
            lines.append(
                f"| **{kat.opis}** | {kat.liczba_faktur} | {kat.suma_netto:,.2f} zł | **{kat.suma_vat_odliczony:,.2f} zł** | {kat.udzial_w_odliczeniu_procent:.1f}% |"
            )

        lines.append("\n## 3. Zestawienie Miesięczne")
        lines.append("| Miesiąc | VAT należny (sprzedaż) | VAT odliczony (koszty) | Do zapłaty US |")
        lines.append("|:---|:---:|:---:|:---:|")
        for m in self.zestawienie_miesieczne:
            lines.append(
                f"| {m['miesiac']} | {Decimal(m['vat_nalezny']):,.2f} zł | **{Decimal(m['vat_odliczony']):,.2f} zł** | {m['do_zaplaty_zaokr']} zł |"
            )

        return "\n".join(lines)


class VATAggregator:
    """
    Deterministyczny agregator odliczeń podatku VAT.
    """

    @staticmethod
    def classify_business_category(sprzedawca_nazwa: str, opis_pozycji: str = "") -> tuple:
        nazwa = sprzedawca_nazwa.upper()
        opis = opis_pozycji.upper()

        if any(
            k in nazwa
            for k in [
                "ORLEN",
                "VOLCER",
                "M&M",
                "CIRCLE K",
                "ANWIM",
                "MOYA",
                "MOL",
                "INTER CARS",
                "BP EUROPA",
                "ACME",
                "SHELL",
            ]
        ):
            return ("SAMOCHOD", "🚗 Samochód (paliwo, serwis, myjnie - art. 86a VAT 50%)", "50%")

        if any(
            k in nazwa
            for k in [
                "ACTION",
                "AMAZON",
                "EURO-NET",
                "ELMAK",
                "GMM GROUP",
                "HUGO",
                "TRADING AUTOMOTIVE",
                "AMPQ",
                "SKY SCAFF",
                "X-KOM",
                "KOMPUTRONIK",
                "MORELE",
            ]
        ):
            return ("SPRZET_IT", "🖥️ Sprzęt komputerowy, monitory i elektronika (100% VAT)", "100%")

        if "WIŚNIEWSKI" in nazwa or "SOFTWARE" in nazwa or "DEVELOPMENT" in nazwa or "PROGRAMISTA" in opis:
            return ("USLUGI_IT", "💻 Usługi programistyczne i podwykonawcy IT (100% VAT)", "100%")

        if any(k in nazwa for k in ["NESPRESSO", "NESTLE", "M. ŚWIDWA", "AMS M."]) or "KAWA" in opis or "BĘBEN" in opis:
            return ("BIURO_KAWA", "☕ Kawa, artykuły biurowe i zaopatrzenie", "100%")

        if any(k in nazwa for k in ["P4", "PLAY", "VIKING", "ORANGE", "T-MOBILE", "PLUS"]):
            return ("TELEKOMUNIKACJA", "📱 Telekomunikacja i Internet mobilny", "MIX")

        if any(
            k in nazwa
            for k in ["INFAKT", "ADMIN.NET.PL", "OVH", "CYBERFOLKS", "HETZNER", "AWS", "GOOGLE CLOUD", "AZURE"]
        ):
            return ("HOSTING_SAAS", "☁️ Narzędzia IT, hosting, chmura i księgowość", "100%")

        if any(k in nazwa for k in ["SECURITUM", "SZKOLENI", "COURSERA", "UDEMY"]):
            return ("SZKOLENIA", "🎓 Szkolenia i rozwój zawodowy IT", "100%")

        return ("INNE", "📦 Pozostałe koszty operacyjne", "100%")

    @classmethod
    def aggregate(
        cls, base_dir: Union[str, Path], nip_or_folder: str, rok: str = "2026", miesiace: Optional[List[str]] = None
    ) -> VATAggregationReport:
        base_path = Path(base_dir)
        target_dir = None

        if (base_path / nip_or_folder).is_dir():
            target_dir = base_path / nip_or_folder
        else:
            candidates = list(base_path.glob(f"{nip_or_folder}*"))
            if candidates and candidates[0].is_dir():
                target_dir = candidates[0]

        if not target_dir or not target_dir.is_dir():
            raise FileNotFoundError(f"Nie znaleziono katalogu firmy dla: {nip_or_folder} w {base_dir}")

        rozliczenia_dir = target_dir / "rozliczenia" / str(rok)
        if not rozliczenia_dir.is_dir():
            raise FileNotFoundError(f"Brak rozliczeń dla roku {rok} w {rozliczenia_dir}")

        pattern = str(rozliczenia_dir / "*/rozliczenie.json")
        json_files = sorted(glob.glob(pattern))

        if miesiace:
            json_files = [f for f in json_files if Path(f).parent.name in miesiace]

        kategorie_podatkowe = {
            "FIRMOWY_100": CategoryAggregation("FIRMOWY_100", "Koszty operacyjne (100% VAT)", "100%"),
            "SAMOCHOD_50": CategoryAggregation("SAMOCHOD_50", "Samochód osobowy – tryb mieszany (50% VAT)", "50%"),
            "PRYWATNY_0": CategoryAggregation("PRYWATNY_0", "Wydatki osobiste / prywatne (0% VAT)", "0%"),
        }

        kategorie_biznesowe: Dict[str, CategoryAggregation] = {}

        zamkniete_miesiace = []
        laczny_vat_odliczony = Decimal("0.00")
        laczny_vat_nalezy = Decimal("0.00")
        laczny_vat_zaplacony_us = Decimal("0.00")
        laczny_vat_z_faktur = Decimal("0.00")
        laczny_vat_nieodliczony = Decimal("0.00")
        zestawienie_miesieczne = []

        firma_nazwa = ""
        firma_nip = ""

        for f_path in json_files:
            m_code = Path(f_path).parent.name
            zamkniete_miesiace.append(m_code)

            with open(f_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)

            if not firma_nazwa:
                firma_nazwa = data.get("firma", target_dir.name)
                firma_nip = data.get("nip", target_dir.name.split("-")[0])

            vat_info = data.get("vat", {})
            vat_odl = Decimal(str(vat_info.get("vat_naliczony", "0.00")))
            vat_nal = Decimal(str(vat_info.get("vat_nalezny", "0.00")))
            vat_zap = Decimal(str(vat_info.get("vat_do_zaplaty_zaokraglony", "0")))

            laczny_vat_odliczony += vat_odl
            laczny_vat_nalezy += vat_nal
            laczny_vat_zaplacony_us += vat_zap

            zestawienie_miesieczne.append(
                {
                    "miesiac": f"{rok}/{m_code}",
                    "vat_nalezny": str(vat_nal),
                    "vat_odliczony": str(vat_odl),
                    "do_zaplaty_zaokr": int(vat_zap),
                }
            )

            # Analiza rejestru zakupów VAT
            zakupy = data.get("ewidencja", {}).get("rejestr_vat", {}).get("zakupy", {})
            wpisy = zakupy.get("wpisy", [])

            for w in wpisy:
                sprzedawca = w.get("sprzedawca_nazwa", "").strip()
                netto = Decimal(str(w.get("suma_netto", "0.00")))
                vat_fv = Decimal(str(w.get("suma_vat_z_faktury", "0.00")))
                vat_wpisu_odl = Decimal(str(w.get("vat_naliczony_do_odliczenia", "0.00")))
                vat_wpisu_nieodl = Decimal(str(w.get("vat_nieodliczony", "0.00")))
                prop = str(w.get("proporcja_odliczenia", "1.00"))

                laczny_vat_z_faktur += vat_fv
                laczny_vat_nieodliczony += vat_wpisu_nieodl

                # Kwalifikacja podatkowa
                if prop == "0.50":
                    kat_p = kategorie_podatkowe["SAMOCHOD_50"]
                elif prop == "0.00":
                    kat_p = kategorie_podatkowe["PRYWATNY_0"]
                else:
                    kat_p = kategorie_podatkowe["FIRMOWY_100"]

                kat_p.liczba_faktur += 1
                kat_p.suma_netto += netto
                kat_p.suma_vat_z_faktur += vat_fv
                kat_p.suma_vat_odliczony += vat_wpisu_odl
                kat_p.suma_vat_nieodliczony += vat_wpisu_nieodl

                # Kategoria biznesowa
                cat_key, cat_name, cat_prop = cls.classify_business_category(sprzedawca)
                if cat_key not in kategorie_biznesowe:
                    kategorie_biznesowe[cat_key] = CategoryAggregation(cat_key, cat_name, cat_prop)

                b_cat = kategorie_biznesowe[cat_key]
                b_cat.liczba_faktur += 1
                b_cat.suma_netto += netto
                b_cat.suma_vat_z_faktur += vat_fv
                b_cat.suma_vat_odliczony += vat_wpisu_odl
                b_cat.suma_vat_nieodliczony += vat_wpisu_nieodl

            # Sprawdzenie pozycji odrzuconych prywatnych w audycie
            odrz_netto = Decimal(str(data.get("ewidencja", {}).get("laczne_odrzucone_netto_prywatne", "0.00")))
            odrz_vat = Decimal(str(data.get("ewidencja", {}).get("laczny_odrzucony_vat_prywatny", "0.00")))
            if odrz_netto > 0 or odrz_vat > 0:
                kat_p_priv = kategorie_podatkowe["PRYWATNY_0"]
                kat_p_priv.suma_netto += odrz_netto
                kat_p_priv.suma_vat_z_faktur += odrz_vat

        # Obliczenie udziałów procentowych
        if laczny_vat_odliczony > 0:
            for kp in kategorie_podatkowe.values():
                kp.udzial_w_odliczeniu_procent = (kp.suma_vat_odliczony / laczny_vat_odliczony) * Decimal("100")
            for kb in kategorie_biznesowe.values():
                kb.udzial_w_odliczeniu_procent = (kb.suma_vat_odliczony / laczny_vat_odliczony) * Decimal("100")

        return VATAggregationReport(
            nip=firma_nip,
            firma=firma_nazwa,
            rok=str(rok),
            zamkniete_miesiace=zamkniete_miesiace,
            laczny_vat_odliczony=laczny_vat_odliczony,
            laczny_vat_nalezy=laczny_vat_nalezy,
            laczny_vat_zaplacony_us=laczny_vat_zaplacony_us,
            laczny_vat_z_faktur_kosztowych=laczny_vat_z_faktur,
            laczny_vat_nieodliczony=laczny_vat_nieodliczony,
            kategorie_podatkowe=kategorie_podatkowe,
            kategorie_biznesowe=kategorie_biznesowe,
            zestawienie_miesieczne=zestawienie_miesieczne,
        )
