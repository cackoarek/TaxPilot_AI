"""
Moduł generowania oficjalnego raportu rozliczenia podatkowego (rozliczenie.md)
oraz prezentacji Paczki Przelewów Podatnika.
"""

from typing import TYPE_CHECKING, Any

from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_deduplicator import DuplicateType

if TYPE_CHECKING:
    pass


class SettlementMarkdownReporter:
    """Generuje czytelny raport rozliczenia i paczki przelewów w formacie Markdown."""

    @classmethod
    def generate(cls, result: Any) -> str:
        linie = [
            f"# Raport Rozliczenia Miesięcznego – {result.rok}-{result.miesiac}",
            f"**Firma:** {result.profil.nazwa} (NIP: `{result.profil.nip}`)",
            f"**Forma opodatkowania:** {result.profil.forma_opodatkowania.value} | **ZUS:** {result.profil.zus.typ.value}",
            "",
            "---",
            "## 1. Paczka Przelewów Podatkowych (Do wykonania)",
            "",
            "| Odbiorca / Zobowiązanie | Kwota do zapłaty | Termin płatności | Rachunek docelowy | Tytuł przelewu |",
            "| :--- | :---: | :---: | :--- | :--- |",
        ]

        for p in result.paczka_przelewow:
            linie.append(
                f"| **{p.nazwa}** | **{p.kwota:.2f} zł** | `{p.termin_platnosci}` | {p.rachunek_docelowy} | `{p.tytul_przelewu}` |"
            )

        linie.extend(
            [
                "",
                f"**Łączna suma obciążeń za ten miesiąc:** **{result.suma_wszystkich_zobowiazan:.2f} zł**",
                "",
                "---",
                "## 2. Zestawienie Ewidencji Gospodarczej",
                f"* **Przychód netto w miesiącu:** {result.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł",
                f"* **Przychód roczny narastająco:** {result.przychod_roczny_narastajaco:.2f} zł (próg zdrowotnej: `{result.zus.prog_przychodow_zdrowotna}`)",
                f"* **Liczba faktur sprzedaży:** {len(result.ledger.ewidencja_przychodow.wpisy)}",
                f"* **Liczba faktur kosztowych:** {len(result.ledger.rejestr_vat.wpisy_zakupow)}",
                "",
                "---",
                "## 3. Szczegóły Wyliczeń",
                "",
                "### A. Składki ZUS",
                f"* **Podstawa składek społecznych:** {result.zus.podstawa_spoleczne:.2f} zł",
                f"* **Składki społeczne (emerytalna, rentowa, chorobowa, wypadkowa, FP):** {result.zus.suma_spoleczne:.2f} zł (w tym odliczalne w PIT bez FP: {result.zus.spoleczne_odliczalne:.2f} zł)",
                f"* **Podstawa składki zdrowotnej:** {result.zus.podstawa_zdrowotna:.2f} zł",
                f"* **Składka zdrowotna:** {result.zus.zdrowotna:.2f} zł (odliczenie na ryczałcie 50%: {result.zus.odliczenie_zdrowotna_ryczalt_50:.2f} zł)",
                f"* **Razem przelew do ZUS:** **{result.zus.lacznie_do_zaplaty:.2f} zł**",
                "",
            ]
        )

        if result.pit28:
            linie.extend(
                [
                    "### B. Ryczałt od Przychodów Ewidencjonowanych (PIT-28)",
                    f"* **Przychód do opodatkowania:** {result.pit28.przychod_laczny:.2f} zł",
                    f"* **Odliczenie składek społecznych (zapłacone w m-cu, bez FP):** -{result.pit28.odliczenie_spoleczne:.2f} zł",
                    f"* **Odliczenie 50% zapłaconej składki zdrowotnej:** -{result.pit28.odliczenie_zdrowotna_50:.2f} zł",
                    f"* **Podstawa opodatkowania:** {result.pit28.podstawa_opodatkowania:.2f} zł",
                    f"* **Podatek wyliczony dokładnie:** {result.pit28.podatek_nalezy_dokladny:.2f} zł",
                    f"* **Zaliczka PIT-28 do zapłaty (zaokrąglona):** **{result.pit28.zaliczka_pit28_zaokraglona} zł**",
                    "",
                ]
            )

        if result.vat:
            linie.extend(
                [
                    "### C. Rozliczenie Podatku VAT (JPK_V7)",
                    f"* **VAT należny (ze sprzedaży):** {result.vat.vat_nalezy:.2f} zł",
                    f"* **VAT naliczony (z kosztów podlegających odliczeniu):** {result.vat.vat_naliczony:.2f} zł",
                    f"* **Różnica VAT:** {result.vat.roznica_vat:.2f} zł",
                ]
            )
            if result.vat.vat_do_zaplaty_zaokraglony > 0:
                linie.append(f"* **Podatek VAT do wpłaty do US:** **{result.vat.vat_do_zaplaty_zaokraglony} zł**")
            else:
                linie.append(
                    f"* **Nadwyżka VAT do przeniesienia na kolejny miesiąc:** **{result.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł**"
                )
            linie.append("")

        # 4. Wyłączenia wydatków osobistych
        odrzucone_pozycje = []
        for audyt in result.ledger.audyt_kosztow:
            for p in audyt.pozycje_wyniki:
                if p.kwalifikacja.value == "PRYWATNY_0":
                    odrzucone_pozycje.append((audyt.numer_faktury, audyt.sprzedawca_nazwa, p))

        if odrzucone_pozycje:
            linie.extend(
                [
                    "---",
                    "## 4. Wyłączenia Wydatków Osobistych (Ochrona Podatkowa)",
                    "Poniższe pozycje zostały wykluczone z kosztów i rejestru VAT jako wydatki prywatne/osobiste:",
                    "",
                    "| Faktura | Kontrahent | Wykluczona pozycja | Kwota netto | VAT (nieodliczony) | Uzasadnienie |",
                    "| :--- | :--- | :--- | :---: | :---: | :--- |",
                ]
            )
            for nr, kontrahent, p in odrzucone_pozycje:
                linie.append(
                    f"| `{nr}` | {kontrahent} | **{p.opis}** | {p.wartosc_netto:.2f} zł | {p.kwota_vat:.2f} zł | {p.uzasadnienie} |"
                )
            linie.extend(
                [
                    "",
                    f"*Łącznie wykluczono z VAT:* **{result.ledger.laczny_odrzucony_vat_prywatny:.2f} zł** (kwota ta nie powiększyła VAT-u naliczonego).",
                    "",
                ]
            )

        # 5. Pytania do przedsiębiorcy
        if result.ledger.pytania_do_uzytkownika:
            linie.extend(
                [
                    "---",
                    "## ⚠️ Pozycje Wymagające Wyjaśnienia (Human-in-the-Loop)",
                    "Przed ostatecznym zamknięciem deklaracji potwierdź kwalifikację poniższych pozycji:",
                    "",
                ]
            )
            for q in result.ledger.pytania_do_uzytkownika:
                linie.append(f"* {q}")
            linie.append("")

        # 6. Wykryte i wykluczone duplikaty dokumentów
        if result.ledger.duplikaty:
            linie.extend(
                [
                    "---",
                    "## 🚨 Wykryte i Zneutralizowane Duplikaty Dokumentów",
                    "Wykryto zdublowane dokumenty, które zostały bezpiecznie pominięte w rozliczeniu (ochrona przed podwójnym odliczeniem podatku i kosztu):",
                    "",
                    "| Lp. | Wykryty plik / dokument | Kontrahent | Kwota brutto | Typ kolizji | Działanie systemu i ochrona |",
                    "| :---: | :--- | :--- | :---: | :---: | :--- |",
                ]
            )
            for idx, d in enumerate(result.ledger.duplikaty, start=1):
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
                plik_odrz = (
                    f"`{d.plik_zrodlowy_odrzucony}`" if d.plik_zrodlowy_odrzucony else f"`{d.faktura_odrzucona.numer}`"
                )
                linie.append(
                    f"| {idx} | {plik_odrz} (nr: `{d.faktura_odrzucona.numer}`) | {kontrahent_info} | {d.faktura_odrzucona.suma_brutto:.2f} zł | {typ_label} | {d.rekomendacja} |"
                )
            linie.extend(
                [
                    "",
                    f"*Łącznie zneutralizowano:* **{len(result.ledger.duplikaty)}** zdublowanych plików. Wszystkie zidentyfikowane kolizje i duplikaty zostały pomyślnie zneutralizowane zgodnie z regułami deduplikacji.",
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
