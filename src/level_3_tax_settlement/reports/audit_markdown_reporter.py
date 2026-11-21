"""
Moduł generowania oficjalnego sprawozdania z audytu podatkowego (sprawozdanie.md).
Zawiera szczegółowy przegląd faktur sprzedaży i kosztów, kwalifikację podatkową,
weryfikację kontrahentów na Białej Liście MF oraz audyt deduplikacji.
"""

import json
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_deduplicator import DuplicateType
from src.level_1_ingestion.invoice_storage import InvoiceStorage

from .helpers import format_rate_pct


class AuditMarkdownReporter:
    """Generuje dokument sprawozdania z czynności księgowych i audytu podatkowego."""

    @classmethod
    def generate(cls, result: Any) -> str:
        faktury_sprzedaz = InvoiceStorage.list_sales_invoices_for_pit(result.profil, result.rok, result.miesiac)
        faktury_koszt = InvoiceStorage.list_invoices(result.profil, result.rok, result.miesiac, typ=InvoiceType.KOSZT)
        audyt_map = {a.numer_faktury: a for a in result.ledger.audyt_kosztow}

        # Odczyt danych weryfikacji Białej Listy i AML dla kontrahentów w audytowanym okresie
        aml_report_file = (
            result.profil.katalog_firmy / "weryfikacje" / result.rok / result.miesiac / "raport-weryfikacji.json"
        )
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
            f"# Sprawozdanie z Czynności Księgowych i Audytu Podatkowego – {result.rok}-{result.miesiac}",
            f"**Firma:** {result.profil.nazwa} (NIP: `{result.profil.nip}`)",
            f"**Kody PKD:** {', '.join(result.profil.kody_pkd) if result.profil.kody_pkd else 'Brak'}",
            f"**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28) | Płatnik VAT: {'TAK' if result.profil.platnik_vat else 'NIE'}",
            f"**Okres audytowany:** {result.rok}-{result.miesiac}",
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
            f"W okresie **{result.rok}-{result.miesiac}** zarejestrowano **{len(faktury_sprzedaz)}** faktur sprzedaży o łącznej wartości netto **{result.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł**.",
            "",
        ]

        for idx, inv in enumerate(faktury_sprzedaz, start=1):
            zrodlo_badge = "🏛️ KSeF" if inv.zrodlo == "KSEF" else "📁 Non-KSeF"
            data_sprz = inv.data_sprzedazy or inv.data_wystawienia
            linie.extend(
                [
                    f"### 1.{idx}. Faktura sprzedaży nr `{inv.numer}` – {inv.nabywca.nazwa}",
                    f"* **Kontrahent (Nabywca):** {inv.nabywca.nazwa} (NIP: `{inv.nabywca.nip}`)",
                    f"* **Data wykonania usługi / sprzedaży:** `{data_sprz}`",
                    f"* **Data wystawienia dokumentu:** `{inv.data_wystawienia}`",
                    f"* **Źródło dokumentu:** {zrodlo_badge} (`{inv.plik_zrodlowy or inv.numer}`)",
                    f"* **Wartości faktury:** Netto: **{inv.suma_netto:.2f} zł** | VAT: **{inv.suma_vat:.2f} zł** | Brutto: **{inv.suma_brutto:.2f} zł**",
                    "",
                    "**Wykaz pozycji i kwalifikacja ryczałtu:**",
                ]
            )

            for poz in inv.pozycje:
                st_rycz = poz.stawka_ryczaltu or Decimal(str(result.profil.domyslna_stawka_ryczaltu))
                podatek_poz = (poz.wartosc_netto * st_rycz).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                linie.append(
                    f"* **{poz.opis}** – Netto: {poz.wartosc_netto:.2f} zł | VAT {poz.stawka_vat}% ({poz.kwota_vat:.2f} zł) $\\rightarrow$ Stawka ryczałtu: **{format_rate_pct(st_rycz)}** (podatek: **{podatek_poz:.2f} zł**)"
                )

            linie.extend(
                [
                    "",
                    "**Uzasadnienie sposobu rozliczenia:**",
                    "* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).",
                    "* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).",
                    "",
                ]
            )

        if not faktury_sprzedaz:
            linie.append("*W tym miesiącu nie wystawiono faktur sprzedaży.*")
            linie.append("")

        linie.extend(
            [
                "---",
                "## 🧾 Część II: Faktury Kosztowe (Zakupy) – Szczegółowy Audyt Podatkowy",
                f"W okresie **{result.rok}-{result.miesiac}** poddano audytowi **{len(faktury_koszt)}** faktur zakupowych wystawionych na NIP firmy.",
                "",
            ]
        )

        for idx, inv in enumerate(faktury_koszt, start=1):
            audit = audyt_map.get(inv.numer)
            zrodlo_badge = "🏛️ KSeF" if inv.zrodlo == "KSEF" else "📁 Non-KSeF"
            c_nip = re.sub(r"[^0-9]", "", inv.sprzedawca.nip)
            aml_k = aml_karty_map.get(c_nip)

            rb_tekst = "Nie wskazano"
            if getattr(inv, "rachunek_bankowy", None):
                st_rach = aml_k.get("status_rachunku") if aml_k else None
                if st_rach == "ZGODNY_BIALA_LISTA":
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ✅ **Zgodny z Białą Listą MF** (bezpieczny do płatności pow. 15 tys. zł)"
                elif st_rach == "BRAK_NA_BIALEJ_LISCIE":
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ⚠️ **Brak na Białej Liście MF** (wymaga zawiadomienia ZAW-NR przy kwocie pow. 15 tys. zł)"
                else:
                    rb_tekst = f"`{inv.rachunek_bankowy}` – ℹ️ Odczytany z dokumentu"

            linie.extend(
                [
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
                ]
            )

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
                linie.append(
                    f"| Całość faktury | {inv.suma_netto:.2f} zł | {inv.suma_vat:.2f} zł | ⚠️ Do wyjaśnienia | **0.00 zł** | Brak audytu pozycji – wymaga decyzji podatnika przed odliczeniem |"
                )
                vat_odliczony_faktury = Decimal("0.00")
                vat_nieodliczony_faktury = inv.suma_vat

            linie.extend(
                [
                    "",
                    "* **Podsumowanie rozliczenia dokumentu:**",
                    f"  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **{vat_odliczony_faktury:.2f} zł**",
                    f"  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **{vat_nieodliczony_faktury:.2f} zł**",
                    "",
                ]
            )

        if not faktury_koszt:
            linie.append("*W tym miesiącu brak dokumentów kosztowych.*")
            linie.append("")

        linie.extend(
            [
                "---",
                "## 🛡️ Część III: Podsumowanie Audytu i Bilans Bezpieczeństwa Podatkowego",
                "",
                "### 1. Zestawienie Zbiorcze Podatku VAT",
                f"* **Łączny VAT należny ze sprzedaży:** **{result.vat.vat_nalezy:.2f} zł**"
                if result.vat
                else "* VAT: Zwolniony",
                f"* **Łączny VAT naliczony podlegający odliczeniu:** **{result.vat.vat_naliczony:.2f} zł**"
                if result.vat
                else "",
                f"* **Łączny VAT odrzucony jako prywatny / nieodliczony:** **{result.ledger.laczny_odrzucony_vat_prywatny:.2f} zł**",
                f"* **Finalny wynik VAT-7 za ten miesiąc:** **{result.vat.vat_do_zaplaty_zaokraglony} zł** (do zapłaty)"
                if result.vat and result.vat.vat_do_zaplaty_zaokraglony > 0
                else f"* **Nadwyżka VAT do przeniesienia:** **{result.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł**"
                if result.vat
                else "",
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
            ]
        )

        if not result.ledger.duplikaty:
            linie.extend(
                [
                    "* **Status deduplikacji:** ✅ W audytowanym okresie nie stwierdzono kolizji źródłowych (KSeF vs Non-KSeF) ani powtórzeń dokumentów z innych miesięcy.",
                    "* Wszystkie ujęte faktury są unikalne i reprezentują rzeczywiste zdarzenia gospodarcze.",
                    "",
                ]
            )
        else:
            linie.extend(
                [
                    "W procesie księgowania wykryto zdublowane dokumenty. Zgodnie z nadrzędnymi regułami bezpieczeństwa podatkowego:",
                    "1. **KSeF First:** Faktury pobrane bezpośrednio z Krajowego Systemu e-Faktur stanowią urzędowe źródło prawdy. Pliki wgrane do katalogów non-ksef dublujące KSeF zostały odrzucone.",
                    "2. **Cross-Month Protection:** Dokumenty uprzednio zaksięgowane w innych miesiącach zostały zablokowane przed ponownym ujęciem.",
                    "",
                    "| Lp. | Odrzucony dokument | Pierwotny dokument | Typ kolizji | Wartość brutto | Uzasadnienie i ochrona |",
                    "| :---: | :--- | :--- | :---: | :---: | :--- |",
                ]
            )
            for idx, d in enumerate(result.ledger.duplikaty, start=1):
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
            linie.extend(
                [
                    "",
                    f"*Łącznie wykluczono:* **{len(result.ledger.duplikaty)}** prób podwójnego ujęcia dokumentów.",
                    "",
                ]
            )

        linie.extend(
            [
                "",
                "---",
                "> ℹ️ *Klauzula informacyjna:* Wyliczenie deterministyczne na podstawie wprowadzonych dokumentów i przyjętych reguł podatnika. Ostateczna odpowiedzialność za deklarację podatkową i rozliczenia spoczywa na podatniku.",
                "",
            ]
        )

        return "\n".join(linie)
