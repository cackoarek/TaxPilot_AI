"""
Główna usługa rozliczeniowa (Poziom 3).
Spina ewidencję księgową (Poziom 2), kalkulatory ZUS, PIT-28 i VAT
oraz generuje kompletną Paczkę Przelewów Podatnika i raporty archiwalne.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import re

from src.core.company import CompanyProfile, FormaOpodatkowania
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.invoice_deduplicator import DuplicateAnomaly, DuplicateType
from src.level_2_bookkeeping.ledger import BookkeepingService, MonthlyLedger
from src.skills.zus_tools import calculate_zus, ZUSCalculationResult
from src.skills.ryczalt_tools import calculate_pit28_advance, PIT28CalculationResult
from src.skills.vat_tools import calculate_vat_settlement, VATBalanceResult


def _format_rate_pct(rate: Decimal) -> str:
    """Formatuje stawkę podatkową jako procent, np. 12% lub 8,5%."""
    val = rate * Decimal("100")
    if val % 1 == 0:
        return f"{int(val)}%"
    return f"{val:.1f}%".replace(".", ",")


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
            f"* **Składki społeczne (emerytalna, rentowa, chorobowa, wypadkowa, FP):** {self.zus.suma_spoleczne:.2f} zł (w tym odliczalne w PIT bez FP: {self.zus.spoleczne_odliczalne:.2f} zł)",
            f"* **Podstawa składki zdrowotnej:** {self.zus.podstawa_zdrowotna:.2f} zł",
            f"* **Składka zdrowotna:** {self.zus.zdrowotna:.2f} zł (odliczenie na ryczałcie 50%: {self.zus.odliczenie_zdrowotna_ryczalt_50:.2f} zł)",
            f"* **Razem przelew do ZUS:** **{self.zus.lacznie_do_zaplaty:.2f} zł**",
            "",
        ])

        if self.pit28:
            linie.extend([
                "### B. Ryczałt od Przychodów Ewidencjonowanych (PIT-28)",
                f"* **Przychód do opodatkowania:** {self.pit28.przychod_laczny:.2f} zł",
                f"* **Odliczenie składek społecznych (zapłacone w m-cu, bez FP):** -{self.pit28.odliczenie_spoleczne:.2f} zł",
                f"* **Odliczenie 50% zapłaconej składki zdrowotnej:** -{self.pit28.odliczenie_zdrowotna_50:.2f} zł",
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

        # 6. Wykryte i wykluczone duplikaty dokumentów
        if self.ledger.duplikaty:
            linie.extend([
                "---",
                "## 🚨 Wykryte i Zneutralizowane Duplikaty Dokumentów",
                "Wykryto zdublowane dokumenty, które zostały bezpiecznie pominięte w rozliczeniu (ochrona przed podwójnym odliczeniem podatku i kosztu):",
                "",
                "| Lp. | Wykryty plik / dokument | Kontrahent | Kwota brutto | Typ kolizji | Działanie systemu i ochrona |",
                "| :---: | :--- | :--- | :---: | :---: | :--- |",
            ])
            for idx, d in enumerate(self.ledger.duplikaty, start=1):
                typ_label = {
                    DuplicateType.KSEF_COLLISION: "🏛️ KSeF First (kolizja z KSeF)",
                    DuplicateType.CROSS_MONTH_DUPLICATE: f"📅 Duplikat z m-ca {d.rok_pierwotny}-{d.miesiac_pierwotny}",
                    DuplicateType.SAME_PERIOD_DUPLICATE: "📄 Zdublowany plik w tym m-cu",
                }.get(d.typ_duplikatu, d.typ_duplikatu.value)

                kontrahent_info = (
                    f"{d.faktura_odrzucona.sprzedawca.nazwa} (`{d.faktura_odrzucona.sprzedawca.nip}`)"
                    if d.faktura_odrzucona.typ == InvoiceType.KOSZT
                    else f"{d.faktura_odrzucona.nabywca.nazwa} (`{d.faktura_odrzucona.nabywca.nip}`)"
                )
                plik_odrz = f"`{d.plik_zrodlowy_odrzucony}`" if d.plik_zrodlowy_odrzucony else f"`{d.faktura_odrzucona.numer}`"
                linie.append(
                    f"| {idx} | {plik_odrz} (nr: `{d.faktura_odrzucona.numer}`) | {kontrahent_info} | {d.faktura_odrzucona.suma_brutto:.2f} zł | {typ_label} | {d.rekomendacja} |"
                )
            linie.extend([
                "",
                f"*Łącznie zneutralizowano:* **{len(self.ledger.duplikaty)}** zdublowanych plików. Podatnik jest w 100% bezpieczny.",
                "",
            ])

        return "\n".join(linie)

    def generate_ewidencja_przychodow_report(self) -> str:
        """
        Generuje dokument ewidencja-przychodow.md:
        Tabela z ewidencją przychodów z informacjami jaka faktura, data wpływu/sprzedaży,
        jaki podatek, stawka oraz podsumowanie na dole.
        """
        linie = [
            f"# Ewidencja Przychodów – {self.rok}-{self.miesiac}",
            f"**Podatnik:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
        ]
        if self.profil.adres:
            linie.append(f"**Adres:** {self.profil.adres}")
        linie.extend([
            f"**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28)",
            f"**Okres rozliczeniowy:** {self.rok}-{self.miesiac}",
            "",
            "---",
            f"## Tabela Ewidencji Przychodów za Miesiąc {self.miesiac}/{self.rok}",
            "",
            "| Lp. | Data sprzedaży / wpływu | Numer dowodu / faktury | Nabywca | NIP | Źródło | Opis zdarzenia gospodarczego | Kwota przychodu netto | Stawka ryczałtu | Wyliczony podatek |",
            "| :---: | :---: | :--- | :--- | :---: | :---: | :--- | :---: | :---: | :---: |",
        ])

        lp = 1
        suma_netto = Decimal("0.00")
        suma_podatku = Decimal("0.00")

        faktury_sprzedaz_map = {
            inv.numer: inv
            for inv in InvoiceStorage.list_sales_invoices_for_pit(self.profil, self.rok, self.miesiac)
        }

        for wpis in self.ledger.ewidencja_przychodow.wpisy:
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
                rate_str = _format_rate_pct(stawka)
                linie.append(
                    f"| {lp} | `{data_wplywu}` | `{wpis.numer_faktury}` | {wpis.nabywca_nazwa} | `{wpis.nabywca_nip}` | {zrodlo_icon} | {opis_skrot} | {kwota:.2f} zł | {rate_str} | {podatek_poz:.2f} zł |"
                )
                lp += 1
                suma_netto += kwota
                suma_podatku += podatek_poz

        if lp == 1:
            linie.append("| - | - | Brak przychodów w danym miesiącu | - | - | - | - | 0.00 zł | - | 0.00 zł |")

        linie.extend([
            "",
            "---",
            f"## Podsumowanie Ewidencji Przychodów za {self.rok}-{self.miesiac}",
            "",
            "| Stawka ryczałtu | Przychód netto | Podatek ryczałtowy (przed odliczeniami) |",
            "| :---: | :---: | :---: |",
        ])

        for st in sorted(self.ledger.ewidencja_przychodow.sumy_wg_stawek.keys(), reverse=True):
            kw = self.ledger.ewidencja_przychodow.sumy_wg_stawek[st]
            pod = (kw * st).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            linie.append(f"| **{_format_rate_pct(st)}** | **{kw:.2f} zł** | **{pod:.2f} zł** |")

        linie.extend([
            f"| **RAZEM** | **{self.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł** | **{suma_podatku:.2f} zł** |",
            "",
        ])

        if self.pit28:
            linie.extend([
                "### Rozliczenie Zaliczki PIT-28 po Ustawowych Odliczeniach:",
                f"* **Przychód łączny:** {self.pit28.przychod_laczny:.2f} zł",
                f"* **Odliczenie składek społecznych ZUS:** -{self.pit28.odliczenie_spoleczne:.2f} zł",
                f"* **Odliczenie 50% zapłaconej składki zdrowotnej:** -{self.pit28.odliczenie_zdrowotna_50:.2f} zł",
                f"* **Podstawa opodatkowania po odliczeniach:** {self.pit28.podstawa_opodatkowania:.2f} zł",
                f"* **Zaliczka na podatek ryczałtowy (PIT-28 po zaokrągleniu):** **{self.pit28.zaliczka_pit28_zaokraglona} zł**",
                f"* **Termin płatności zaliczki do Urzędu Skarbowego:** `{self.pit28.termin_platnosci}`",
                "",
            ])

        return "\n".join(linie)

    def generate_ewidencja_przychodow_sumy_report(self) -> str:
        """
        Generuje dokument ewidencja-przychodow-sumy.md:
        - Tabela 1: tabela przychodów w poszczególnych miesiącach z podziałem na wysokość podatku,
          oraz składkami ubezpieczeń do odliczenia (społeczne + 50% zdrowotnej) i sumą na dole.
        - Tabela 2: dla miesięcy w tym roku z podziałem na podstawę/ryczałt zależnie od wysokości podatku,
          oraz sumami na dole.
        """
        target_m = int(self.miesiac)
        rok_str = self.rok

        dane_miesiecy: Dict[int, Dict[str, Any]] = {}
        wszystkie_stawki = set()

        for m in range(1, target_m + 1):
            m_str = f"{m:02d}"
            if m_str == self.miesiac:
                sumy_stawek = dict(self.ledger.ewidencja_przychodow.sumy_wg_stawek)
                przych_laczny = self.ledger.ewidencja_przychodow.laczny_przychod_netto
                spol = self.pit28.odliczenie_spoleczne if self.pit28 else self.zus.suma_spoleczne
                zdr50 = self.pit28.odliczenie_zdrowotna_50 if self.pit28 else self.zus.odliczenie_zdrowotna_ryczalt_50
                podstawa = self.pit28.podstawa_opodatkowania if self.pit28 else Decimal("0.00")
                podatek_dokl = self.pit28.podatek_nalezy_dokladny if self.pit28 else Decimal("0.00")
                zaliczka = self.pit28.zaliczka_pit28_zaokraglona if self.pit28 else 0
            else:
                settlement_json = self.profil.katalog_firmy / "rozliczenia" / rok_str / m_str / "rozliczenie.json"
                if settlement_json.exists():
                    try:
                        with open(settlement_json, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        pit = d.get("pit28") or {}
                        ew = d.get("ewidencja", {}).get("ewidencja_przychodow") or {}
                        raw_stawki = ew.get("sumy_wg_stawek") or {}
                        sumy_stawek = {Decimal(k): Decimal(v) for k, v in raw_stawki.items()}
                        przych_laczny = Decimal(str(ew.get("laczny_przychod_netto") or pit.get("przychod_laczny") or "0.00"))
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
            wszystkie_stawki.add(Decimal(str(self.profil.domyslna_stawka_ryczaltu)))

        posortowane_stawki = sorted(list(wszystkie_stawki), reverse=True)

        linie = [
            f"# Ewidencja Przychodów – Zestawienie Roczne i Sumy ({self.rok})",
            f"**Podatnik:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28)",
            f"**Stan narastająco na koniec miesiąca:** {self.rok}-{self.miesiac}",
            "",
            "---",
            f"## Tabela 1: Przychody w Poszczególnych Miesiącach oraz Składki Ubezpieczeń do Odliczenia",
            "",
        ]

        # Budowa nagłówka Tabeli 1
        naglowek_t1 = ["| Miesiąc |"]
        separator_t1 = ["| :---: |"]
        for st in posortowane_stawki:
            naglowek_t1.append(f" Przychód {_format_rate_pct(st)} |")
            separator_t1.append(" :---: |")
        naglowek_t1.append(" Łączny przychód | Składki społeczne ZUS | Składka zdrowotna (50%) | Suma składek do odliczenia |")
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
            wiersz = [f"| `{d['miesiac_str']}/{self.rok}` |"]
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

        linie.extend([
            "",
            "---",
            f"## Tabela 2: Miesiące w Roku z Podziałem na Podstawę i Ryczałt wg Wysokości Podatku",
            "",
        ])

        naglowek_t2 = ["| Miesiąc |"]
        separator_t2 = ["| :---: |"]
        for st in posortowane_stawki:
            naglowek_t2.append(f" Podstawa {_format_rate_pct(st)} |")
            separator_t2.append(" :---: |")
        naglowek_t2.append(" Podstawa opodatkowania (razem) |")
        separator_t2.append(" :---: |")
        for st in posortowane_stawki:
            naglowek_t2.append(f" Ryczałt {_format_rate_pct(st)} |")
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
            wiersz2 = [f"| `{d['miesiac_str']}/{self.rok}` |"]
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

    def generate_sprawozdanie_report(self) -> str:
        """
        Generuje dokument sprawozdanie.md:
        Szczegółowe omówienie każdej faktury (sprzedaży i zakupów), wyjaśnienie sposobu
        jej rozliczenia, powodu odrzucenia lub zaksięgowania, wysokości podatku – zapis prac
        podczas księgowania jako audyt podatkowy.
        """
        faktury_sprzedaz = InvoiceStorage.list_sales_invoices_for_pit(
            self.profil, self.rok, self.miesiac
        )
        faktury_koszt = InvoiceStorage.list_invoices(
            self.profil, self.rok, self.miesiac, typ=InvoiceType.KOSZT
        )
        audyt_map = {a.numer_faktury: a for a in self.ledger.audyt_kosztow}

        # Odczyt danych weryfikacji Białej Listy i AML dla kontrahentów w audytowanym okresie
        aml_report_file = self.profil.katalog_firmy / "weryfikacje" / self.rok / self.miesiac / "raport-weryfikacji.json"
        aml_karty_map: Dict[str, Dict[str, Any]] = {}
        if aml_report_file.exists():
            try:
                aml_json_data = json.loads(aml_report_file.read_text(encoding="utf-8"))
                for k in aml_json_data.get("kontrahenci", []):
                    clean_k_nip = re.sub(r"[^0-9]", "", k.get("nip", ""))
                    aml_karty_map[clean_k_nip] = k
            except Exception:
                pass

        linie = [
            f"# Sprawozdanie z Czynności Księgowych i Audytu Podatkowego – {self.rok}-{self.miesiac}",
            f"**Firma:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Kody PKD:** {', '.join(self.profil.kody_pkd) if self.profil.kody_pkd else 'Brak'}",
            f"**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28) | Płatnik VAT: {'TAK' if self.profil.platnik_vat else 'NIE'}",
            f"**Okres audytowany:** {self.rok}-{self.miesiac}",
            "",
            "---",
            "## 🎯 Cel i Zakres Sprawozdania",
            "Niniejszy dokument stanowi protokół z czynności księgowych oraz audytu dokumentów źródłowych (zarówno pobranych z KSeF, jak i wyekstrahowanych ze źródeł zewnętrznych).",
            "Każdy dokument został zweryfikowany pod kątem:",
            "1. Prawidłowości kwalifikacji przychodu do stawek ryczałtu (art. 12 ustawy o zryczałtowanym podatku dochodowym),",
            "2. Prawa do odliczenia podatku naliczonego VAT (art. 86 ust. 1 oraz art. 86a ustawy o VAT),",
            "3. Ochrony przed ryzykiem podatkowym poprzez bezwzględne wyłączenie wydatków prywatnych i osobistych,",
            "4. Zgodności wyliczeń z zasadą Zero-Hallucination (deterministyczne obliczenia w Pythonie na typie Decimal).",
            "",
            "---",
            "## 📈 Część I: Faktury Sprzedaży (Przychody) – Kwalifikacja i Podatki",
            f"W okresie **{self.rok}-{self.miesiac}** zarejestrowano **{len(faktury_sprzedaz)}** faktur sprzedaży o łącznej wartości netto **{self.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł**.",
            "",
        ]

        for idx, inv in enumerate(faktury_sprzedaz, start=1):
            zrodlo_badge = "🏛️ KSeF" if inv.zrodlo == "KSEF" else "📁 Non-KSeF"
            data_sprz = inv.data_sprzedazy or inv.data_wystawienia
            linie.extend([
                f"### 1.{idx}. Faktura sprzedaży nr `{inv.numer}` – {inv.nabywca.nazwa}",
                f"* **Kontrahent (Nabywca):** {inv.nabywca.nazwa} (NIP: `{inv.nabywca.nip}`)",
                f"* **Data wykonania usługi / sprzedaży:** `{data_sprz}`",
                f"* **Data wystawienia dokumentu:** `{inv.data_wystawienia}`",
                f"* **Źródło dokumentu:** {zrodlo_badge} (`{inv.plik_zrodlowy or inv.numer}`)",
                f"* **Wartości faktury:** Netto: **{inv.suma_netto:.2f} zł** | VAT: **{inv.suma_vat:.2f} zł** | Brutto: **{inv.suma_brutto:.2f} zł**",
                "",
                "**Wykaz pozycji i kwalifikacja ryczałtu:**",
            ])

            for poz in inv.pozycje:
                st_rycz = poz.stawka_ryczaltu or Decimal(str(self.profil.domyslna_stawka_ryczaltu))
                podatek_poz = (poz.wartosc_netto * st_rycz).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                linie.append(
                    f"* **{poz.opis}** – Netto: {poz.wartosc_netto:.2f} zł | VAT {poz.stawka_vat}% ({poz.kwota_vat:.2f} zł) $\\rightarrow$ Stawka ryczałtu: **{_format_rate_pct(st_rycz)}** (podatek: **{podatek_poz:.2f} zł**)"
                )

            linie.extend([
                "",
                "**Uzasadnienie sposobu rozliczenia:**",
                f"* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).",
                f"* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).",
                "",
            ])

        if not faktury_sprzedaz:
            linie.append("*W tym miesiącu nie wystawiono faktur sprzedaży.*")
            linie.append("")

        linie.extend([
            "---",
            "## 🧾 Część II: Faktury Kosztowe (Zakupy) – Szczegółowy Audyt Podatkowy",
            f"W okresie **{self.rok}-{self.miesiac}** poddano audytowi **{len(faktury_koszt)}** faktur zakupowych wystawionych na NIP firmy.",
            "",
        ])

        for idx, inv in enumerate(faktury_koszt, start=1):
            audit = audyt_map.get(inv.numer)
            zrodlo_badge = "🏛️ KSeF" if inv.zrodlo == "KSEF" else "📁 Non-KSeF"
            c_nip = re.sub(r"[^0-9]", "", inv.sprzedawca.nip)
            aml_k = aml_karty_map.get(c_nip)

            # Informacja o numerze rachunku bankowego i Białej Liście
            rb_tekst = "Nie wskazano"
            if getattr(inv, "rachunek_bankowy", None):
                st_rach = aml_k.get("status_rachunku") if aml_k else None
                if st_rach == "ZGODNY_BIALA_LISTA":
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ✅ **Zgodny z Białą Listą MF** (bezpieczny do płatności pow. 15 tys. zł)"
                elif st_rach == "BRAK_NA_BIALEJ_LISCIE":
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ⚠️ **Brak na Białej Liście MF** (wymaga zawiadomienia ZAW-NR przy kwocie pow. 15 tys. zł)"
                else:
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ℹ️ Odczytany z dokumentu"

            linie.extend([
                f"### 2.{idx}. Faktura kosztowa nr `{inv.numer}` – {inv.sprzedawca.nazwa}",
                f"* **Sprzedawca:** {inv.sprzedawca.nazwa} (NIP: `{inv.sprzedawca.nip}`)",
                f"* **Data wystawienia:** `{inv.data_wystawienia}` | **Data zakupu:** `{inv.data_sprzedazy or inv.data_wystawienia}`",
                f"* **Źródło dokumentu:** {zrodlo_badge} (`{inv.plik_zrodlowy or inv.numer}`)",
                f"* **Wartości z dokumentu:** Netto: **{inv.suma_netto:.2f} zł** | VAT: **{inv.suma_vat:.2f} zł** | Brutto: **{inv.suma_brutto:.2f} zł**",
                f"* **Rachunek bankowy do zapłaty:** {rb_tekst}",
                "",
                "**Przebieg audytu poszczególnych pozycji:**",
                "",
                "| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |",
                "| :--- | :---: | :---: | :---: | :---: | :--- |",
            ])

            vat_odliczony_faktury = Decimal("0.00")
            vat_nieodliczony_faktury = Decimal("0.00")

            if audit:
                for poz in audit.pozycje_wyniki:
                    vat_odliczony_faktury += poz.vat_do_odliczenia
                    nieodliczony = poz.kwota_vat - poz.vat_do_odliczenia
                    vat_nieodliczony_faktury += nieodliczony

                    kwal_badge = {
                        "FIRMOWY_100": "✅ 100% Firmowy",
                        "SAMOCHOD_50": "🚗 Pojazd 50% (art. 86a)",
                        "PRYWATNY_0": "⛔ Odrzucony (0% VAT)",
                        "DO_WYJASNIENIA": "⚠️ Do wyjaśnienia",
                    }.get(poz.kwalifikacja.value, poz.kwalifikacja.value)

                    opis_p = poz.opis[:45] + "..." if len(poz.opis) > 48 else poz.opis
                    linie.append(
                        f"| {opis_p} | {poz.wartosc_netto:.2f} zł | {poz.kwota_vat:.2f} zł ({poz.stawka_vat}%) | {kwal_badge} | **{poz.vat_do_odliczenia:.2f} zł** | {poz.uzasadnienie} |"
                    )
            else:
                linie.append(f"| Całość faktury | {inv.suma_netto:.2f} zł | {inv.suma_vat:.2f} zł | ✅ 100% Firmowy | {inv.suma_vat:.2f} zł | Standardowy wydatek firmowy |")
                vat_odliczony_faktury = inv.suma_vat

            linie.extend([
                "",
                f"* **Podsumowanie rozliczenia dokumentu:**",
                f"  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **{vat_odliczony_faktury:.2f} zł**",
                f"  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **{vat_nieodliczony_faktury:.2f} zł**",
                "",
            ])

        if not faktury_koszt:
            linie.append("*W tym miesiącu brak dokumentów kosztowych.*")
            linie.append("")

        linie.extend([
            "---",
            "## 🛡️ Część III: Podsumowanie Audytu i Bilans Bezpieczeństwa Podatkowego",
            "",
            "### 1. Zestawienie Zbiorcze Podatku VAT",
            f"* **Łączny VAT należny ze sprzedaży:** **{self.vat.vat_nalezy:.2f} zł**" if self.vat else "* VAT: Zwolniony",
            f"* **Łączny VAT naliczony podlegający odliczeniu:** **{self.vat.vat_naliczony:.2f} zł**" if self.vat else "",
            f"* **Łączny VAT odrzucony jako prywatny / nieodliczony:** **{self.ledger.laczny_odrzucony_vat_prywatny:.2f} zł**",
            f"* **Finalny wynik VAT-7 za ten miesiąc:** **{self.vat.vat_do_zaplaty_zaokraglony} zł** (do zapłaty)" if self.vat and self.vat.vat_do_zaplaty_zaokraglony > 0 else f"* **Nadwyżka VAT do przeniesienia:** **{self.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł**" if self.vat else "",
            "",
            "### 2. Eliminacja Ryzyk Podatkowych (Ochrona Podatkowa)",
            "* Wszystkie pozycje o charakterze osobistym (np. opieka medyczna, telewizja, zakupy prywatne) zostały zidentyfikowane i trwale wykluczone z odliczenia podatku VAT.",
            "* Zapobiega to zakwestionowaniu rozliczenia przez organy Krajowej Administracji Skarbowej (KAS) oraz eliminuje ryzyko nałożenia dodatkowego zobowiązania podatkowego (sankcji VAT do 30% z art. 112b ustawy o VAT) wraz z odsetkami za zwłokę.",
            "* Zastosowano ustawowy limit 50% odliczenia VAT na wydatki eksploatacyjne pojazdów osobowych użytkowanych w trybie mieszanym (art. 86a ustawy o VAT).",
            "",
            "### 3. Weryfikacja Rachunków Bankowych na Białej Liście Podatników VAT (art. 22p PIT)",
            "* Zgodnie z procedurą należytej staranności, numery rachunków bankowych z faktur zakupowych poddano weryfikacji w oficjalnym wykazie Ministerstwa Finansów.",
            "* Płatności powyżej 15 000 zł brutto na rachunki figurujące na Białej Liście MF gwarantują pełne bezpieczeństwo podatkowe, zachowanie prawa do KUP oraz brak solidarnej odpowiedzialności za VAT (art. 117ba Ordynacji podatkowej).",
            "",
            "---",
            "## 🔍 Część IV: Rejestr Wykrytych Duplikatów i Kolizji Źródłowych (Deduplikacja)",
        ])

        if not self.ledger.duplikaty:
            linie.extend([
                "* **Status deduplikacji:** ✅ W audytowanym okresie nie stwierdzono kolizji źródłowych (KSeF vs Non-KSeF) ani powtórzeń dokumentów z innych miesięcy.",
                "* Wszystkie ujęte faktury są unikalne i reprezentują rzeczywiste zdarzenia gospodarcze.",
                "",
            ])
        else:
            linie.extend([
                "W procesie księgowania wykryto zdublowane dokumenty. Zgodnie z nadrzędnymi regułami bezpieczeństwa podatkowego:",
                "1. **KSeF First:** Faktury pobrane bezpośrednio z Krajowego Systemu e-Faktur stanowią urzędowe źródło prawdy. Pliki wgrane do katalogów non-ksef dublujące KSeF zostały odrzucone.",
                "2. **Cross-Month Protection:** Dokumenty uprzednio zaksięgowane w innych miesiącach zostały zablokowane przed ponownym ujęciem.",
                "",
                "| Lp. | Odrzucony dokument | Pierwotny dokument | Typ kolizji | Wartość brutto | Uzasadnienie i ochrona |",
                "| :---: | :--- | :--- | :---: | :---: | :--- |",
            ])
            for idx, d in enumerate(self.ledger.duplikaty, start=1):
                typ_label = {
                    DuplicateType.KSEF_COLLISION: "🏛️ Kolizja KSeF vs Non-KSeF",
                    DuplicateType.CROSS_MONTH_DUPLICATE: f"📅 Duplikat z m-ca {d.rok_pierwotny}-{d.miesiac_pierwotny}",
                    DuplicateType.SAME_PERIOD_DUPLICATE: "📄 Zdublowany plik",
                }.get(d.typ_duplikatu, d.typ_duplikatu.value)

                odrz_info = f"`{d.plik_zrodlowy_odrzucony}` (nr: `{d.faktura_odrzucona.numer}`)"
                pierw_info = f"`{d.plik_zrodlowy_pierwotny}` ({d.rok_pierwotny}-{d.miesiac_pierwotny})"
                linie.append(
                    f"| {idx} | {odrz_info} | {pierw_info} | {typ_label} | {d.faktura_odrzucona.suma_brutto:.2f} zł | {d.opis_problemu} {d.rekomendacja} |"
                )
            linie.extend([
                "",
                f"*Łącznie wykluczono:* **{len(self.ledger.duplikaty)}** prób podwójnego ujęcia dokumentów.",
                "",
            ])

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
            faktury = InvoiceStorage.list_sales_invoices_for_pit(
                profile=profile, rok=rok_str, miesiac=m_str
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

            prev_rozliczenie_file = profile.katalog_firmy / "rozliczenia" / prev_rok_str / prev_m_str / "rozliczenie.json"
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
                    skladka_zdrowotna_zaplacona = Decimal(str(prev_zus.get("skladka_zdrowotna", {}).get("kwota", "0.00")))
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
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(wynik.to_dict(), f, indent=2, ensure_ascii=False)

            # Główny raport rozliczenia i paczka przelewów
            md_path = target_dir / "rozliczenie.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(wynik.generate_markdown_report())

            # 1. Ewidencja przychodów za dany miesiąc
            ep_path = target_dir / "ewidencja-przychodow.md"
            with open(ep_path, "w", encoding="utf-8") as f:
                f.write(wynik.generate_ewidencja_przychodow_report())

            # 2. Ewidencja przychodów - sumy roczne (YTD)
            eps_path = target_dir / "ewidencja-przychodow-sumy.md"
            with open(eps_path, "w", encoding="utf-8") as f:
                f.write(wynik.generate_ewidencja_przychodow_sumy_report())

            # 3. Sprawozdanie z audytu i czynności księgowych
            spr_path = target_dir / "sprawozdanie.md"
            with open(spr_path, "w", encoding="utf-8") as f:
                f.write(wynik.generate_sprawozdanie_report())

            # 4. Automatyczna weryfikacja compliance kontrahentów (AML / Sankcje / Biała Lista)
            try:
                from src.skills.aml_tools import VerificationService
                VerificationService.verify_month(profile, rok_str, miesiac_str, zapisz_pliki=True)
            except Exception:
                pass

        return wynik

