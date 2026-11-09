"""
Moduł weryfikacji i audytu dokumentów przed ostatecznym rozliczeniem podatkowym (Pre-settlement Review).
Generuje deterministyczne zestawienia:
1. Faktury przychodowe (sprzedaż) – do zaznajomienia się i weryfikacji kompletności.
2. Faktury kosztowe (zakupy) – do weryfikacji przynależności i akceptacji przez przedsiębiorcę.
3. Pozycje i faktury do wyjaśnienia – pozycje niejednoznaczne (DO_WYJASNIENIA) oraz wykluczenia prywatne (PRYWATNY_0).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Any

from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType, Invoice
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.skills.ryczalt_tools import RegulySprzedazyFirmy
from src.skills.cost_classifier import (
    RegulyKosztoweFirmy,
    audit_invoice_expense,
    InvoiceTaxAuditReport,
    KwalifikacjaKosztu,
    PozycjaKwalifikacjaResult,
)


@dataclass
class SalesItemReview:
    """Pozycja faktury sprzedaży w zestawieniu przychodów."""
    lp: int
    data: str
    numer: str
    nabywca_nazwa: str
    nabywca_nip: str
    przedmiot: str
    kwota_netto: Decimal
    stawka_ryczaltu: Decimal
    kwota_vat: Decimal
    kwota_brutto: Decimal
    zrodlo: str = "KSeF"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "zrodlo": self.zrodlo,
            "data": self.data,
            "numer": self.numer,
            "nabywca_nazwa": self.nabywca_nazwa,
            "nabywca_nip": self.nabywca_nip,
            "przedmiot": self.przedmiot,
            "kwota_netto": str(self.kwota_netto),
            "stawka_ryczaltu": str(self.stawka_ryczaltu),
            "kwota_vat": str(self.kwota_vat),
            "kwota_brutto": str(self.kwota_brutto),
        }


@dataclass
class ExpenseItemReview:
    """Faktura kosztowa w zestawieniu zakupów do weryfikacji przez przedsiębiorcę."""
    lp: int
    data: str
    numer: str
    sprzedawca_nazwa: str
    sprzedawca_nip: str
    glowny_przedmiot: str
    kwota_netto: Decimal
    kwota_vat: Decimal
    kwota_brutto: Decimal
    kwalifikacja_podatkowa: str
    status_weryfikacji: str
    zrodlo: str = "KSeF"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "zrodlo": self.zrodlo,
            "data": self.data,
            "numer": self.numer,
            "sprzedawca_nazwa": self.sprzedawca_nazwa,
            "sprzedawca_nip": self.sprzedawca_nip,
            "glowny_przedmiot": self.glowny_przedmiot,
            "kwota_netto": str(self.kwota_netto),
            "kwota_vat": str(self.kwota_vat),
            "kwota_brutto": str(self.kwota_brutto),
            "kwalifikacja_podatkowa": self.kwalifikacja_podatkowa,
            "status_weryfikacji": self.status_weryfikacji,
        }


@dataclass
class ClarificationItemReview:
    """Pozycja kosztowa wymagająca wyjaśnienia lub zatwierdzenia przez przedsiębiorcę."""
    lp: int
    numer_faktury: str
    kontrahent_nazwa: str
    kontrahent_nip: str
    pozycja_opis: str
    kwota_netto: Decimal
    kwota_vat: Decimal
    status: str
    uzasadnienie: str
    pytanie_do_uzytkownika: str
    sugerowana_odpowiedz: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lp": self.lp,
            "numer_faktury": self.numer_faktury,
            "kontrahent_nazwa": self.kontrahent_nazwa,
            "kontrahent_nip": self.kontrahent_nip,
            "pozycja_opis": self.pozycja_opis,
            "kwota_netto": str(self.kwota_netto),
            "kwota_vat": str(self.kwota_vat),
            "status": self.status,
            "uzasadnienie": self.uzasadnienie,
            "pytanie_do_uzytkownika": self.pytanie_do_uzytkownika,
            "sugerowana_odpowiedz": self.sugerowana_odpowiedz,
        }


@dataclass
class PreSettlementReview:
    """Kompletny raport weryfikacyjny przed ostatecznym rozliczeniem miesiąca."""
    profil: CompanyProfile
    rok: str
    miesiac: str
    sprzedaz: List[SalesItemReview] = field(default_factory=list)
    koszty: List[ExpenseItemReview] = field(default_factory=list)
    do_wyjasnienia: List[ClarificationItemReview] = field(default_factory=list)
    laczna_sprzedaz_netto: Decimal = Decimal("0.00")
    laczna_sprzedaz_vat: Decimal = Decimal("0.00")
    laczna_sprzedaz_brutto: Decimal = Decimal("0.00")
    laczny_koszt_netto: Decimal = Decimal("0.00")
    laczny_koszt_vat: Decimal = Decimal("0.00")
    laczny_koszt_brutto: Decimal = Decimal("0.00")

    @classmethod
    def build(cls, profile: CompanyProfile, rok: str, miesiac: str) -> "PreSettlementReview":
        """Tworzy deterministyczny raport przeglądu dokumentów za podany miesiąc."""
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        # 1. Automatyczna ekstrakcja dokumentów spoza KSeF (sprzedaż i koszty) z non-ksef-raw/ do non-ksef-extracted/
        NonKSeFExtractor.extract_all(profile, rok_str, miesiac_str)

        # 2. Faktury sprzedaży
        reguly_sprzedazy = RegulySprzedazyFirmy.load(profile)
        faktury_sprzedaz = InvoiceStorage.list_invoices(
            profile=profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.SPRZEDAZ
        )
        domyslna_stawka_ryczaltu = Decimal(str(profile.domyslna_stawka_ryczaltu))

        sales_items: List[SalesItemReview] = []
        suma_sprzedaz_netto = Decimal("0.00")
        suma_sprzedaz_vat = Decimal("0.00")
        suma_sprzedaz_brutto = Decimal("0.00")

        for idx, inv in enumerate(faktury_sprzedaz, start=1):
            przedmiot = ", ".join([p.opis for p in inv.pozycje]) if inv.pozycje else "Usługi IT"
            if len(przedmiot) > 55:
                przedmiot = przedmiot[:52] + "..."

            buyer_stawka = None
            if inv.pozycje and inv.pozycje[0].stawka_ryczaltu is not None:
                buyer_stawka = inv.pozycje[0].stawka_ryczaltu
            else:
                buyer_stawka = reguly_sprzedazy.stawki_nabywcow.get(inv.nabywca.nip, domyslna_stawka_ryczaltu)

            zrodlo_val = "Non-KSeF" if getattr(inv, "zrodlo", "") == "NON_KSEF" else "KSeF"

            sales_items.append(
                SalesItemReview(
                    lp=idx,
                    data=inv.data_wystawienia,
                    numer=inv.numer,
                    nabywca_nazwa=inv.nabywca.nazwa,
                    nabywca_nip=inv.nabywca.nip,
                    przedmiot=przedmiot,
                    kwota_netto=inv.suma_netto,
                    stawka_ryczaltu=buyer_stawka,
                    kwota_vat=inv.suma_vat,
                    kwota_brutto=inv.suma_brutto,
                    zrodlo=zrodlo_val,
                )
            )
            suma_sprzedaz_netto += inv.suma_netto
            suma_sprzedaz_vat += inv.suma_vat
            suma_sprzedaz_brutto += inv.suma_brutto

        # 3. Faktury kosztowe i audyt
        faktury_koszt = InvoiceStorage.list_invoices(
            profile=profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.KOSZT
        )
        reguly_firmy = RegulyKosztoweFirmy.load(profile)

        expense_items: List[ExpenseItemReview] = []
        clarification_items: List[ClarificationItemReview] = []
        suma_koszt_netto = Decimal("0.00")
        suma_koszt_vat = Decimal("0.00")
        suma_koszt_brutto = Decimal("0.00")

        clarification_idx = 1
        for idx, inv in enumerate(faktury_koszt, start=1):
            audit = audit_invoice_expense(inv, reguly_firmy, kody_pkd=profile.kody_pkd)
            opis_glowny = ", ".join([p.opis for p in inv.pozycje[:3]]) if inv.pozycje else "Zakup towarów/usług"
            if len(opis_glowny) > 50:
                opis_glowny = opis_glowny[:47] + "..."

            # Ocena kwalifikacji ogólnej faktury
            kwalifikacje = [p.kwalifikacja for p in audit.pozycje_wyniki]
            if any(k == KwalifikacjaKosztu.DO_WYJASNIENIA for k in kwalifikacje):
                kwal_tekst = "⚠️ Wymaga wyjaśnienia"
                status_tekst = "Wymaga decyzji"
            elif any(k == KwalifikacjaKosztu.PRYWATNY_0 for k in kwalifikacje) and any(k == KwalifikacjaKosztu.FIRMOWY_100 for k in kwalifikacje):
                kwal_tekst = "Mieszana (wykluczenia prywatne)"
                status_tekst = "Do akceptacji"
            elif all(k == KwalifikacjaKosztu.PRYWATNY_0 for k in kwalifikacje):
                kwal_tekst = "⛔ Prywatny (0% VAT/KUP)"
                status_tekst = "Wykluczona"
            elif all(k == KwalifikacjaKosztu.SAMOCHOD_50 for k in kwalifikacje):
                kwal_tekst = "🚗 Samochód 50% (art. 86a)"
                status_tekst = "Do akceptacji"
            elif all(k == KwalifikacjaKosztu.FIRMOWY_100 for k in kwalifikacje):
                kwal_tekst = "✅ 100% Firmowy"
                status_tekst = "Do akceptacji"
            else:
                kwal_tekst = "Częściowo odliczalny"
                status_tekst = "Do akceptacji"

            zrodlo_val = "Non-KSeF" if getattr(inv, "zrodlo", "") == "NON_KSEF" else "KSeF"
            expense_items.append(
                ExpenseItemReview(
                    lp=idx,
                    data=inv.data_wystawienia,
                    numer=inv.numer,
                    sprzedawca_nazwa=inv.sprzedawca.nazwa,
                    sprzedawca_nip=inv.sprzedawca.nip,
                    glowny_przedmiot=opis_glowny,
                    kwota_netto=inv.suma_netto,
                    kwota_vat=inv.suma_vat,
                    kwota_brutto=inv.suma_brutto,
                    kwalifikacja_podatkowa=kwal_tekst,
                    status_weryfikacji=status_tekst,
                    zrodlo=zrodlo_val,
                )
            )
            suma_koszt_netto += inv.suma_netto
            suma_koszt_vat += inv.suma_vat
            suma_koszt_brutto += inv.suma_brutto

            # Wykrycie pozycji do wyjaśnienia lub pozycji prywatnych do zatwierdzenia
            for p in audit.pozycje_wyniki:
                if p.kwalifikacja == KwalifikacjaKosztu.DO_WYJASNIENIA:
                    clarification_items.append(
                        ClarificationItemReview(
                            lp=clarification_idx,
                            numer_faktury=inv.numer,
                            kontrahent_nazwa=inv.sprzedawca.nazwa,
                            kontrahent_nip=inv.sprzedawca.nip,
                            pozycja_opis=p.opis,
                            kwota_netto=p.wartosc_netto,
                            kwota_vat=p.kwota_vat,
                            status="DO_WYJASNIENIA",
                            uzasadnienie="Niejednoznaczny opis pozycji w fakturze.",
                            pytanie_do_uzytkownika=f"Pozycja '{p.opis}' ({p.wartosc_netto:.2f} zł netto) – czy zaliczyć do kosztów firmy (np. stałe IP/usługa serwerowa), czy jest to wydatek prywatny?",
                            sugerowana_odpowiedz="Określ: 'firmowe 100%' lub 'prywatne 0%'.",
                        )
                    )
                    clarification_idx += 1
                elif p.kwalifikacja == KwalifikacjaKosztu.PRYWATNY_0:
                    clarification_items.append(
                        ClarificationItemReview(
                            lp=clarification_idx,
                            numer_faktury=inv.numer,
                            kontrahent_nazwa=inv.sprzedawca.nazwa,
                            kontrahent_nip=inv.sprzedawca.nip,
                            pozycja_opis=p.opis,
                            kwota_netto=p.wartosc_netto,
                            kwota_vat=p.kwota_vat,
                            status="PRYWATNY_0",
                            uzasadnienie=p.uzasadnienie,
                            pytanie_do_uzytkownika=f"Pozycja '{p.opis}' ({p.wartosc_netto:.2f} zł netto) została zakwalifikowana jako wydatek prywatny (0% VAT, 0% KUP). Czy potwierdzasz wykluczenie?",
                            sugerowana_odpowiedz="Napisz: 'potwierdzam wykluczenie' lub wskaż związek gospodarczy z IT.",
                        )
                    )
                    clarification_idx += 1

        return cls(
            profil=profile,
            rok=rok_str,
            miesiac=miesiac_str,
            sprzedaz=sales_items,
            koszty=expense_items,
            do_wyjasnienia=clarification_items,
            laczna_sprzedaz_netto=suma_sprzedaz_netto,
            laczna_sprzedaz_vat=suma_sprzedaz_vat,
            laczna_sprzedaz_brutto=suma_sprzedaz_brutto,
            laczny_koszt_netto=suma_koszt_netto,
            laczny_koszt_vat=suma_koszt_vat,
            laczny_koszt_brutto=suma_koszt_brutto,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nip": self.profil.nip,
            "firma": self.profil.nazwa,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "laczna_sprzedaz_netto": str(self.laczna_sprzedaz_netto),
            "laczna_sprzedaz_vat": str(self.laczna_sprzedaz_vat),
            "laczna_sprzedaz_brutto": str(self.laczna_sprzedaz_brutto),
            "laczny_koszt_netto": str(self.laczny_koszt_netto),
            "laczny_koszt_vat": str(self.laczny_koszt_vat),
            "laczny_koszt_brutto": str(self.laczny_koszt_brutto),
            "sprzedaz": [s.to_dict() for s in self.sprzedaz],
            "koszty": [k.to_dict() for k in self.koszty],
            "do_wyjasnienia": [c.to_dict() for c in self.do_wyjasnienia],
        }

    def generate_markdown(self) -> str:
        """Generuje czytelny raport markdown ze wszystkimi tabelami weryfikacyjnymi."""
        stawka_proc = int(Decimal(str(self.profil.domyslna_stawka_ryczaltu)) * 100)

        linie = [
            f"# 📋 Przegląd Dokumentów Przed Rozliczeniem – {self.rok}-{self.miesiac}",
            f"**Firma:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Forma opodatkowania:** {self.profil.forma_opodatkowania.value} (Stawka ryczałtu: {stawka_proc}%)",
            "**Status weryfikacji:** ⏳ Oczekiwanie na zapoznanie i akceptację przedsiębiorcy",
            "",
            "---",
            f"## 📈 1. Faktury Sprzedaży (Przychody) – Do Zaznajomienia i Weryfikacji Kompletności",
            "Poniższe faktury sprzedaży zostały pobrane z KSeF oraz wyekstrahowane z archiwum non-ksef i zakwalifikowane do przychodów w bieżącym miesiącu:",
            "",
            "| Lp. | Źródło | Data | Numer faktury | Nabywca | NIP | Przedmiot sprzedaży | Netto | Ryczałt | VAT | Brutto |",
            "| :---: | :---: | :---: | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: |",
        ]

        if not self.sprzedaz:
            linie.append("| - | - | - | *Brak faktur sprzedaży w tym miesiącu* | - | - | - | 0.00 zł | - | 0.00 zł | 0.00 zł |")
        else:
            for s in self.sprzedaz:
                zrodlo_badge = "📁 Non-KSeF" if s.zrodlo == "Non-KSeF" else "🏛️ KSeF"
                ryczalt_kwota = (s.kwota_netto * s.stawka_ryczaltu).quantize(Decimal("0.01"))
                s_proc_val = f"{s.stawka_ryczaltu * 100:.2f}".rstrip("0").rstrip(".") + "%"
                linie.append(
                    f"| {s.lp} | {zrodlo_badge} | {s.data} | `{s.numer}` | {s.nabywca_nazwa} | `{s.nabywca_nip}` | {s.przedmiot} | {s.kwota_netto:.2f} zł | {s_proc_val} ({ryczalt_kwota:.2f} zł) | {s.kwota_vat:.2f} zł | {s.kwota_brutto:.2f} zł |"
                )
            linie.append(
                f"| | | | | **SUMA PRZYCHODÓW** | | | **{self.laczna_sprzedaz_netto:.2f} zł** | | **{self.laczna_sprzedaz_vat:.2f} zł** | **{self.laczna_sprzedaz_brutto:.2f} zł** |"
            )

        linie.extend([
            "",
            "> ℹ️ **Weryfikacja kompletności przychodów:**",
            f"> Sprawdź, czy powyższa lista zawiera wszystkie faktury sprzedaży wystawione za okres **{self.rok}-{self.miesiac}**.",
            "> *Czy brakuje jakiejś faktury (np. wystawionej poza KSeF, korygującej lub czekającej na wystawienie)?*",
            "",
            "---",
            f"## 🧾 2. Faktury Kosztowe (Zakupy) – Do Weryfikacji i Akceptacji Przedsiębiorcy",
            "Poniższe faktury kosztowe zostały pobrane z KSeF oraz wyekstrahowane z archiwum non-ksef na NIP Twojej działalności:",
            "",
            "| Lp. | Źródło | Data | Numer faktury | Sprzedawca | NIP | Przedmiot zakupu | Netto | VAT | Brutto | Kwalifikacja podatkowa |",
            "| :---: | :---: | :---: | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :--- |",
        ]        )

        if not self.koszty:
            linie.append("| - | - | - | *Brak faktur kosztowych w tym miesiącu* | - | - | - | 0.00 zł | 0.00 zł | 0.00 zł | - |")
        else:
            for k in self.koszty:
                zrodlo_badge = "📁 Non-KSeF" if k.zrodlo == "Non-KSeF" else "🏛️ KSeF"
                linie.append(
                    f"| {k.lp} | {zrodlo_badge} | {k.data} | `{k.numer}` | {k.sprzedawca_nazwa} | `{k.sprzedawca_nip}` | {k.glowny_przedmiot} | {k.kwota_netto:.2f} zł | {k.kwota_vat:.2f} zł | {k.kwota_brutto:.2f} zł | {k.kwalifikacja_podatkowa} |"
                )
            linie.append(
                f"| | | | | **SUMA WYDATKÓW** | | | **{self.laczny_koszt_netto:.2f} zł** | **{self.laczny_koszt_vat:.2f} zł** | **{self.laczny_koszt_brutto:.2f} zł** | |"
            )

        linie.extend([
            "",
            "> ⚠️ **Weryfikacja przynależności faktur:**",
            "> Sprawdź powyższą listę i potwierdź: *Czy wszystkie te faktury faktycznie należą do Ciebie i dotyczą Twojej działalności gospodarczej?*",
            "> *Czy któraś faktura została wystawiona na Twój NIP pomyłkowo lub nie dotyczy Twojej firmy?*",
            "",
            "---",
            f"## 🔍 3. Pozycje i Faktury Wymagające Wyjaśnienia (Human-in-the-Loop)",
        ])

        if not self.do_wyjasnienia:
            linie.extend([
                "✅ **Wszystkie pozycje kosztowe zostały sklasyfikowane automatycznie bez wątpliwości.**",
                "Brak pozycji o niejasnym statusie lub wymagających dodatkowej decyzji.",
            ])
        else:
            linie.extend([
                "Wykryto pozycje niejednoznaczne lub wykluczone jako wydatki prywatne/osobiste. Przed finalnym rozliczeniem potwierdź decyzje:",
                "",
                "| Lp. | Faktura | Sprzedawca | Pozycja w fakturze | Netto | VAT | Status | Pytanie do Ciebie / Sugestia |",
                "| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |",
            ])
            for c in self.do_wyjasnienia:
                status_icon = "⚠️ DO WYJAŚNIENIA" if c.status == "DO_WYJASNIENIA" else "⛔ PRYWATNY (0% VAT)"
                linie.append(
                    f"| {c.lp} | `{c.numer_faktury}` | {c.kontrahent_nazwa} | **{c.pozycja_opis}** | {c.kwota_netto:.2f} zł | {c.kwota_vat:.2f} zł | `{status_icon}` | {c.pytanie_do_uzytkownika} |"
                )

            linie.extend([
                "",
                "### 💬 Jak odpowiedzieć asystentowi:",
                "Wystarczy, że napiszesz w czacie np.:",
                "* *\"Wszystkie faktury kosztowe są moje. W Play usługi inne to stałe IP serwera (firmowe 100%), a pakiet medyczny to prywatny (potwierdzam wykluczenie).\"*",
                "* *\"W fakturach sprzedaży wszystko się zgadza, niczego nie brakuje – możemy przejść do rozliczenia.\"*",
                "",
                "Asystent automatycznie zapisze nowe reguły w pliku `reguly_kosztowe.json` i przejdzie do deterministycznego wyliczenia podatków.",
            ])

        return "\n".join(linie)

