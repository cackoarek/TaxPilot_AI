"""
Moduł generowania oficjalnych ewidencji przychodów w formacie Markdown:
- ewidencja-przychodow.md (za dany miesiąc)
- ewidencja-przychodow-sumy.md (zestawienie roczne YTD)
"""

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

from src.level_1_ingestion.invoice_storage import InvoiceStorage

from .helpers import format_rate_pct


class LedgerMarkdownReporter:
    """Generuje dokumenty ewidencji przychodów ryczałtowych."""

    @classmethod
    def generate_monthly(cls, result: Any) -> str:
        """
        Generuje dokument ewidencja-przychodow.md:
        Tabela z ewidencją przychodów z informacjami jaka faktura, data wpływu/sprzedaży,
        jaki podatek, stawka oraz podsumowanie na dole.
        """
        linie = [
            f"# Ewidencja Przychodów – {result.rok}-{result.miesiac}",
            f"**Podatnik:** {result.profil.nazwa} (NIP: `{result.profil.nip}`)",
        ]
        if result.profil.adres:
            linie.append(f"**Adres:** {result.profil.adres}")
        linie.extend(
            [
                "**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28)",
                f"**Okres rozliczeniowy:** {result.rok}-{result.miesiac}",
                "",
                "---",
                f"## Tabela Ewidencji Przychodów za Miesiąc {result.miesiac}/{result.rok}",
                "",
                "| Lp. | Data sprzedaży / wpływu | Numer dowodu / faktury | Nabywca | NIP | Źródło | Opis zdarzenia gospodarczego | Kwota przychodu netto | Stawka ryczałtu | Wyliczony podatek |",
                "| :---: | :---: | :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: |",
            ]
        )

        lp = 1
        suma_netto = Decimal("0.00")
        suma_podatku = Decimal("0.00")

        faktury_sprzedaz_map = {
            inv.numer: inv
            for inv in InvoiceStorage.list_sales_invoices_for_pit(result.profil, result.rok, result.miesiac)
        }

        for wpis in result.ledger.ewidencja_przychodow.wpisy:
            inv = faktury_sprzedaz_map.get(wpis.numer_faktury)
            zrodlo_icon = "🏛️ KSeF" if (inv and inv.zrodlo == "KSEF") or wpis.zrodlo == "KSEF" else "📁 Non-KSeF"
            opis = wpis.opis_zdarzenia
            if not opis and inv and inv.pozycje:
                opis = ", ".join(p.opis for p in inv.pozycje if p.opis)
            opis = opis or "Świadczenie usług informatycznych"
            opis_skrot = opis[:57] + "..." if len(opis) > 60 else opis

            data_wplywu = wpis.data_sprzedazy
            if inv and inv.data_wystawienia and inv.data_wystawienia != wpis.data_sprzedazy:
                data_wplywu = f"{wpis.data_sprzedazy} (wyst. {inv.data_wystawienia})"

            for stawka, kwota in wpis.przychody_wg_stawek.items():
                podatek_poz = (kwota * stawka).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                rate_str = format_rate_pct(stawka)
                linie.append(
                    f"| {lp} | `{data_wplywu}` | `{wpis.numer_faktury}` | {wpis.nabywca_nazwa} | `{wpis.nabywca_nip}` | {zrodlo_icon} | {opis_skrot} | {kwota:.2f} zł | {rate_str} | {podatek_poz:.2f} zł |"
                )
                lp += 1
                suma_netto += kwota
                suma_podatku += podatek_poz

        if lp == 1:
            linie.append("| - | - | Brak przychodów w danym miesiącu | - | - | - | - | 0.00 zł | - | 0.00 zł |")

        linie.extend(
            [
                "",
                "---",
                f"## Podsumowanie Ewidencji Przychodów za {result.rok}-{result.miesiac}",
                "",
                "| Stawka ryczałtu | Przychód netto | Podatek ryczałtowy (przed odliczeniami) |",
                "| :---: | :---: | :---: |",
            ]
        )

        for st in sorted(result.ledger.ewidencja_przychodow.sumy_wg_stawek.keys(), reverse=True):
            kw = result.ledger.ewidencja_przychodow.sumy_wg_stawek[st]
            pod = (kw * st).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            linie.append(f"| **{format_rate_pct(st)}** | **{kw:.2f} zł** | **{pod:.2f} zł** |")

        linie.extend(
            [
                f"| **RAZEM** | **{result.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł** | **{suma_podatku:.2f} zł** |",
                "",
            ]
        )

        if result.pit28:
            linie.extend(
                [
                    "### Rozliczenie Zaliczki PIT-28 po Ustawowych Odliczeniach:",
                    f"* **Przychód łączny:** {result.pit28.przychod_laczny:.2f} zł",
                    f"* **Odliczenie składek społecznych ZUS:** -{result.pit28.odliczenie_spoleczne:.2f} zł",
                    f"* **Odliczenie 50% zapłaconej składki zdrowotnej:** -{result.pit28.odliczenie_zdrowotna_50:.2f} zł",
                    f"* **Podstawa opodatkowania po odliczeniach:** {result.pit28.podstawa_opodatkowania:.2f} zł",
                    f"* **Zaliczka na podatek ryczałtowy (PIT-28 po zaokrągleniu):** **{result.pit28.zaliczka_pit28_zaokraglona} zł**",
                    f"* **Termin płatności zaliczki do Urzędu Skarbowego:** `{result.pit28.termin_platnosci}`",
                    "",
                ]
            )

        return "\n".join(linie)

    @classmethod
    def generate_ytd(cls, result: Any) -> str:
        """
        Generuje dokument ewidencja-przychodow-sumy.md:
        - Tabela 1: tabela przychodów w poszczególnych miesiącach z podziałem na wysokość podatku,
          oraz składkami ubezpieczeń do odliczenia (społeczne + 50% zdrowotnej) i sumą na dole.
        - Tabela 2: dla miesięcy w tym roku z podziałem na podstawę/ryczałt zależnie od wysokości podatku,
          oraz sumami na dole.
        """
        target_m = int(result.miesiac)
        rok_str = result.rok

        dane_miesiecy: Dict[int, Dict[str, Any]] = {}
        wszystkie_stawki = set()

        for m in range(1, target_m + 1):
            m_str = f"{m:02d}"
            if m_str == result.miesiac:
                sumy_stawek = dict(result.ledger.ewidencja_przychodow.sumy_wg_stawek)
                przych_laczny = result.ledger.ewidencja_przychodow.laczny_przychod_netto
                spol = result.pit28.odliczenie_spoleczne if result.pit28 else result.zus.suma_spoleczne
                zdr50 = (
                    result.pit28.odliczenie_zdrowotna_50 if result.pit28 else result.zus.odliczenie_zdrowotna_ryczalt_50
                )
                podstawa = result.pit28.podstawa_opodatkowania if result.pit28 else Decimal("0.00")
                podatek_dokl = result.pit28.podatek_nalezy_dokladny if result.pit28 else Decimal("0.00")
                zaliczka = result.pit28.zaliczka_pit28_zaokraglona if result.pit28 else 0
            else:
                settlement_json = result.profil.katalog_firmy / "rozliczenia" / rok_str / m_str / "rozliczenie.json"
                if settlement_json.exists():
                    try:
                        with open(settlement_json, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        pit = d.get("pit28") or {}
                        ew = d.get("ewidencja", {}).get("ewidencja_przychodow") or {}
                        raw_stawki = ew.get("sumy_wg_stawek") or {}
                        sumy_stawek = {Decimal(k): Decimal(v) for k, v in raw_stawki.items()}
                        przych_laczny = Decimal(
                            str(ew.get("laczny_przychod_netto") or pit.get("przychod_laczny") or "0.00")
                        )
                        spol = Decimal(str(pit.get("odliczenie_spoleczne") or "0.00"))
                        zdr50 = Decimal(str(pit.get("odliczenie_zdrowotna_50") or "0.00"))
                        podstawa = Decimal(str(pit.get("podstawa_opodatkowania") or "0.00"))
                        podatek_dokl = Decimal(str(pit.get("podatek_nalezy_dokladny") or "0.00"))
                        zaliczka = int(pit.get("zaliczka_pit28_zaokraglona") or 0)
                    except Exception:
                        sumy_stawek = {}
                        przych_laczny = Decimal("0.00")
                        spol = Decimal("0.00")
                        zdr50 = Decimal("0.00")
                        podstawa = Decimal("0.00")
                        podatek_dokl = Decimal("0.00")
                        zaliczka = 0
                else:
                    sumy_stawek = {}
                    przych_laczny = Decimal("0.00")
                    spol = Decimal("0.00")
                    zdr50 = Decimal("0.00")
                    podstawa = Decimal("0.00")
                    podatek_dokl = Decimal("0.00")
                    zaliczka = 0

            for st in sumy_stawek.keys():
                wszystkie_stawki.add(st)

            dane_miesiecy[m] = {
                "miesiac_str": m_str,
                "sumy_wg_stawek": sumy_stawek,
                "przych_laczny": przych_laczny,
                "spoleczne": spol,
                "zdrowotna_50": zdr50,
                "suma_odliczen": spol + zdr50,
                "podstawa": podstawa,
                "podatek_dokladny": podatek_dokl,
                "zaliczka": zaliczka,
            }

        if not wszystkie_stawki:
            wszystkie_stawki.add(Decimal(str(result.profil.domyslna_stawka_ryczaltu)))

        posortowane_stawki = sorted(list(wszystkie_stawki), reverse=True)

        linie = [
            f"# Ewidencja Przychodów – Zestawienie Roczne i Sumy ({result.rok})",
            f"**Podatnik:** {result.profil.nazwa} (NIP: `{result.profil.nip}`)",
            "**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28)",
            f"**Stan narastająco na koniec miesiąca:** {result.rok}-{result.miesiac}",
            "",
            "---",
            "## Tabela 1: Przychody w Poszczególnych Miesiącach oraz Składki Ubezpieczeń do Odliczenia",
            "",
        ]

        naglowek_t1 = ["| Miesiąc |"]
        separator_t1 = ["| :---: |"]
        for st in posortowane_stawki:
            naglowek_t1.append(f" Przychód {format_rate_pct(st)} |")
            separator_t1.append(" :---: |")
        naglowek_t1.append(
            " Łączny przychód | Składki społeczne ZUS | Składka zdrowotna (50%) | Suma składek do odliczenia |"
        )
        separator_t1.append(" :---: | :---: | :---: | :---: |")

        linie.append("".join(naglowek_t1))
        linie.append("".join(separator_t1))

        suma_przych_per_st = {st: Decimal("0.00") for st in posortowane_stawki}
        suma_laczny_przych = Decimal("0.00")
        suma_spoleczne = Decimal("0.00")
        suma_zdrowotna_50 = Decimal("0.00")
        suma_lacznych_odliczen = Decimal("0.00")

        for m in range(1, target_m + 1):
            d = dane_miesiecy[m]
            wiersz = [f"| `{d['miesiac_str']}/{result.rok}` |"]
            for st in posortowane_stawki:
                kw = d["sumy_wg_stawek"].get(st, Decimal("0.00"))
                wiersz.append(f" {kw:.2f} zł |")
                suma_przych_per_st[st] += kw
            wiersz.append(
                f" **{d['przych_laczny']:.2f} zł** | {d['spoleczne']:.2f} zł | {d['zdrowotna_50']:.2f} zł | **{d['suma_odliczen']:.2f} zł** |"
            )
            linie.append("".join(wiersz))

            suma_laczny_przych += d["przych_laczny"]
            suma_spoleczne += d["spoleczne"]
            suma_zdrowotna_50 += d["zdrowotna_50"]
            suma_lacznych_odliczen += d["suma_odliczen"]

        wiersz_sum_t1 = ["| **SUMA (YTD)** |"]
        for st in posortowane_stawki:
            wiersz_sum_t1.append(f" **{suma_przych_per_st[st]:.2f} zł** |")
        wiersz_sum_t1.append(
            f" **{suma_laczny_przych:.2f} zł** | **{suma_spoleczne:.2f} zł** | **{suma_zdrowotna_50:.2f} zł** | **{suma_lacznych_odliczen:.2f} zł** |"
        )
        linie.append("".join(wiersz_sum_t1))

        linie.extend(
            [
                "",
                "---",
                "## Tabela 2: Miesiące w Roku z Podziałem na Podstawę i Ryczałt wg Wysokości Podatku",
                "",
            ]
        )

        naglowek_t2 = ["| Miesiąc |"]
        separator_t2 = ["| :---: |"]
        for st in posortowane_stawki:
            naglowek_t2.append(f" Podstawa {format_rate_pct(st)} |")
            separator_t2.append(" :---: |")
        naglowek_t2.append(" Podstawa opodatkowania (razem) |")
        separator_t2.append(" :---: |")
        for st in posortowane_stawki:
            naglowek_t2.append(f" Ryczałt {format_rate_pct(st)} |")
            separator_t2.append(" :---: |")
        naglowek_t2.append(" Podatek należny dokładny | Zaliczka PIT-28 (zaokrąglona) |")
        separator_t2.append(" :---: | :---: |")

        linie.append("".join(naglowek_t2))
        linie.append("".join(separator_t2))

        suma_podstawa_per_st = {st: Decimal("0.00") for st in posortowane_stawki}
        suma_podstawa_laczna = Decimal("0.00")
        suma_ryczalt_per_st = {st: Decimal("0.00") for st in posortowane_stawki}
        suma_podatek_dokl = Decimal("0.00")
        suma_zaliczka = 0

        for m in range(1, target_m + 1):
            d = dane_miesiecy[m]
            wiersz2 = [f"| `{d['miesiac_str']}/{result.rok}` |"]
            lacz_p = d["przych_laczny"]
            suma_odl = d["suma_odliczen"]

            podstawy_m: Dict[Decimal, Decimal] = {}
            ryczalty_m: Dict[Decimal, Decimal] = {}
            for st in posortowane_stawki:
                przych_st = d["sumy_wg_stawek"].get(st, Decimal("0.00"))
                if lacz_p > Decimal("0.00"):
                    udzial = przych_st / lacz_p
                    odl_st = (suma_odl * udzial).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    podst_st = max(Decimal("0.00"), przych_st - odl_st)
                else:
                    podst_st = Decimal("0.00")
                rycz_st = (podst_st * st).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                podstawy_m[st] = podst_st
                ryczalty_m[st] = rycz_st
                suma_podstawa_per_st[st] += podst_st
                suma_ryczalt_per_st[st] += rycz_st

            for st in posortowane_stawki:
                wiersz2.append(f" {podstawy_m[st]:.2f} zł |")
            wiersz2.append(f" **{d['podstawa']:.2f} zł** |")
            for st in posortowane_stawki:
                wiersz2.append(f" {ryczalty_m[st]:.2f} zł |")
            wiersz2.append(f" **{d['podatek_dokladny']:.2f} zł** | **{d['zaliczka']} zł** |")
            linie.append("".join(wiersz2))

            suma_podstawa_laczna += d["podstawa"]
            suma_podatek_dokl += d["podatek_dokladny"]
            suma_zaliczka += d["zaliczka"]

        wiersz_sum_t2 = ["| **SUMA ROCZNA** |"]
        for st in posortowane_stawki:
            wiersz_sum_t2.append(f" **{suma_podstawa_per_st[st]:.2f} zł** |")
        wiersz_sum_t2.append(f" **{suma_podstawa_laczna:.2f} zł** |")
        for st in posortowane_stawki:
            wiersz_sum_t2.append(f" **{suma_ryczalt_per_st[st]:.2f} zł** |")
        wiersz_sum_t2.append(f" **{suma_podatek_dokl:.2f} zł** | **{suma_zaliczka} zł** |")
        linie.append("".join(wiersz_sum_t2))

        linie.append("")
        return "\n".join(linie)
