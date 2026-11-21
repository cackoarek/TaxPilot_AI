"""
Silnik księgowania faktur (Poziom 2).
Przetwarza dokumenty z InvoiceStorage i generuje:
- Ewidencję Przychodów (Ryczałt)
- Rejestry VAT (sprzedaż i zakupy)
- Audyt podatkowy pozycji kosztowych (wykluczenie wydatków osobistych, pytania do przedsiębiorcy)
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_deduplicator import DuplicateAnomaly
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from src.skills.cost_classifier import (
    InvoiceTaxAuditReport,
    ReczneKwalifikacjeService,
    RegulyKosztoweFirmy,
    audit_invoice_expense,
)
from src.skills.ryczalt_tools import EwidencjaPrzychodowMiesiaca, RegulySprzedazyFirmy
from src.skills.vat_tools import ProporcjaOdliczeniaVAT, RejestrVATMiesiaca


@dataclass
class MonthlyLedger:
    """Kompletna ewidencja księgowa firmy za dany miesiąc."""

    profil: CompanyProfile
    rok: str
    miesiac: str
    ewidencja_przychodow: EwidencjaPrzychodowMiesiaca
    rejestr_vat: RejestrVATMiesiaca
    audyt_kosztow: List[InvoiceTaxAuditReport] = field(default_factory=list)
    pytania_do_uzytkownika: List[str] = field(default_factory=list)
    duplikaty: List[DuplicateAnomaly] = field(default_factory=list)

    @property
    def laczne_odrzucone_netto_prywatne(self) -> Decimal:
        return sum((a.odrzucone_netto_prywatne for a in self.audyt_kosztow), Decimal("0.00"))

    @property
    def laczny_odrzucony_vat_prywatny(self) -> Decimal:
        return sum((a.odrzucony_vat_prywatny for a in self.audyt_kosztow), Decimal("0.00"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nip": self.profil.nip,
            "firma": self.profil.nazwa,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "ewidencja_przychodow": self.ewidencja_przychodow.to_dict(),
            "rejestr_vat": self.rejestr_vat.to_dict(),
            "audyt_kosztow": [a.to_dict() for a in self.audyt_kosztow],
            "laczne_odrzucone_netto_prywatne": str(self.laczne_odrzucone_netto_prywatne),
            "laczny_odrzucony_vat_prywatny": str(self.laczny_odrzucony_vat_prywatny),
            "pytania_do_uzytkownika": self.pytania_do_uzytkownika,
            "duplikaty": [d.to_dict() for d in self.duplikaty],
        }


class BookkeepingService:
    """
    Serwis orkiestrujący księgowanie dokumentów za dany miesiąc.
    """

    @classmethod
    def process_month(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        custom_vat_proportions: Optional[Dict[str, ProporcjaOdliczeniaVAT]] = None,
    ) -> MonthlyLedger:
        """
        Wczytuje z dysku wszystkie faktury z danego miesiąca i księguje je w ewidencji ryczałtu oraz rejestrach VAT,
        przeprowadzając szczegółowy audyt pozycji kosztowych.
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        ewidencja = EwidencjaPrzychodowMiesiaca(rok=rok_str, miesiac=miesiac_str)
        rejestr_vat = RejestrVATMiesiaca(rok=rok_str, miesiac=miesiac_str)
        audyty_kosztow: List[InvoiceTaxAuditReport] = []
        pytania_uzytkownika: List[str] = []

        # 1. Automatyczna ekstrakcja dokumentów spoza KSeF (sprzedaż i koszty) z non-ksef-raw do non-ksef-extracted
        NonKSeFExtractor.extract_all(profile, rok_str, miesiac_str)

        # 2. Wczytanie reguł kosztowych i sprzedażowych firmy
        reguly_firmy = RegulyKosztoweFirmy.load(profile)
        reguly_sprzedazy = RegulySprzedazyFirmy.load(profile)

        # 3. Wczytanie faktur sprzedaży (KSeF + Non-KSeF)
        # Dla Ewidencji Przychodów (PIT-28) uwzględniamy zasadę ex tunc (korekty wsteczne z powodu błędu rachunkowego - art. 14 ust. 1m PIT)
        faktury_sprzedaz_pit = InvoiceStorage.list_sales_invoices_for_pit(
            profile=profile, rok=rok_str, miesiac=miesiac_str
        )
        # Dla Rejestru VAT sprzedaży uwzględniamy faktury wystawione w danym miesiącu (art. 29a ust. 13 VAT)
        faktury_sprzedaz_vat = InvoiceStorage.list_invoices(
            profile=profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.SPRZEDAZ
        )
        domyslna_stawka_ryczaltu = Decimal(str(profile.domyslna_stawka_ryczaltu))

        for inv in faktury_sprzedaz_pit:
            ewidencja.dodaj_fakture(
                inv, default_rate=domyslna_stawka_ryczaltu, custom_buyer_rates=reguly_sprzedazy.stawki_nabywcow
            )

        if profile.platnik_vat:
            for inv in faktury_sprzedaz_vat:
                rejestr_vat.dodaj_fakture_sprzedazy(inv)

        # 4. Wczytanie i audyt faktur kosztowych (zarówno KSeF jak i Non-KSeF)
        faktury_koszt = InvoiceStorage.list_invoices(
            profile=profile, rok=rok_str, miesiac=miesiac_str, typ=InvoiceType.KOSZT
        )
        reczne_overrides = ReczneKwalifikacjeService.load_overrides(profile, rok_str, miesiac_str)

        custom_vat = custom_vat_proportions or {}
        for inv in faktury_koszt:
            forced_prop = custom_vat.get(inv.numer)
            # Audyt pozycji kosztowych
            report = audit_invoice_expense(
                inv,
                reguly_firmy,
                kody_pkd=profile.kody_pkd,
                reczne_overrides=reczne_overrides,
            )
            audyty_kosztow.append(report)
            if report.wymaga_wyjasnienia:
                pytania_uzytkownika.extend(report.pytania_do_uzytkownika)

            if profile.platnik_vat:
                # Faktury odrzucone w 100% jako wydatki prywatne (np. pakiety medyczne z VAT zw) nie wchodzą do rejestru VAT
                if report.odrzucone_netto_prywatne == inv.suma_netto and report.odrzucony_vat_prywatny == inv.suma_vat:
                    continue
                rejestr_vat.dodaj_fakture_zakupu(inv, forced_ratio=forced_prop, audit_report=report)

        # 5. Wykryte duplikaty i anomalie
        duplikaty = InvoiceStorage.get_duplicate_anomalies(profile, rok_str, miesiac_str)

        return MonthlyLedger(
            profil=profile,
            rok=rok_str,
            miesiac=miesiac_str,
            ewidencja_przychodow=ewidencja,
            rejestr_vat=rejestr_vat,
            audyt_kosztow=audyty_kosztow,
            pytania_do_uzytkownika=pytania_uzytkownika,
            duplikaty=duplikaty,
        )
