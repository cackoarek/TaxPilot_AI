"""
Interfejs wiersza poleceń (CLI) dla TaxPilot AI.
Pozwala na:
- synchronizację faktur z KSeF (Poziom 1)
- rozliczenia podatkowo-składkowe (Poziom 2 & 3)
- symulację form opodatkowania (Poziom 4)
- audyt brakujących kosztów (Poziom 4)
"""

import argparse
import sys
from decimal import Decimal

from src.core.company import CompanyProfile
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_3_tax_settlement.settlement_service import SettlementService
from src.skills.tax_advisor_tools import simulate_tax_regimes, audit_expense_leaks
from src.skills.pre_settlement_review import PreSettlementReview


def cmd_sync(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Rozpoczynam synchronizację z KSeF ({profile.ksef.srodowisko}) dla firmy: {profile.nazwa}...")
    client = KSeFClient(profile)
    summary = client.sync_month_invoices(args.rok, args.miesiac)

    print("\n✅ Synchronizacja zakończona sukcesem!")
    print(f" * Pobranych faktur sprzedaży: {summary['liczba_sprzedazy']} (netto: {summary['suma_sprzedaz_netto']} zł)")
    print(f" * Pobranych faktur kosztowych: {summary['liczba_kosztow']} (netto: {summary['suma_koszty_netto']} zł)")


def cmd_sync_range(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    date_from = f"{args.od}T00:00:00+00:00"
    date_to = f"{args.do}T23:59:59+00:00"
    print(f"Rozpoczynam synchronizację zakresu {args.od} do {args.do} z KSeF ({profile.ksef.srodowisko}) dla {profile.nazwa}...")
    client = KSeFClient(profile)
    summary = client.sync_range_invoices(date_from, date_to)

    print("\n✅ Synchronizacja zakresu zakończona sukcesem!")
    print(f" * Zapisano faktur sprzedaży: {summary['liczba_sprzedazy']} (netto: {summary['suma_sprzedaz_netto']} zł)")
    print(f" * Zapisano faktur kosztowych: {summary['liczba_kosztow']} (netto: {summary['suma_koszty_netto']} zł)")


def cmd_settle(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Obliczam rozliczenie podatkowo-składkowe za {args.rok}-{args.miesiac.zfill(2)}...")
    result = SettlementService.settle_month(
        profile=profile,
        rok=args.rok,
        miesiac=args.miesiac,
        nadwyzka_vat_poprzedni=Decimal(str(args.nadwyzka_vat)),
        zapisz_raporty=True,
    )

    print("\n" + result.generate_markdown_report())


def cmd_settle_year(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Rozpoczynam sekwencyjne rozliczenie roku {args.rok} (od {args.od} do {args.do}) dla firmy: {profile.nazwa}...")
    nadwyzka = Decimal("0.00")
    start_m = int(args.od)
    end_m = int(args.do)

    for m in range(start_m, end_m + 1):
        m_str = f"{m:02d}"
        res = SettlementService.settle_month(
            profile=profile,
            rok=str(args.rok),
            miesiac=m_str,
            nadwyzka_vat_poprzedni=nadwyzka,
            zapisz_raporty=True
        )
        print(f"\n--- Zaksięgowano miesiąc {args.rok}-{m_str} ---")
        print(f" * Przychód: {res.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł (narastająco: {res.przychod_roczny_narastajaco:.2f} zł)")
        print(f" * ZUS: {res.zus.lacznie_do_zaplaty:.2f} zł (termin: {res.zus.termin_platnosci})")
        if res.pit28:
            print(f" * PIT-28 (12%): {res.pit28.zaliczka_pit28_zaokraglona} zł (termin: {res.pit28.termin_platnosci})")
        if res.vat:
            print(f" * VAT do zapłaty: {res.vat.vat_do_zaplaty_zaokraglony} zł (przeniesienie nadwyżki: {res.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł, termin: {res.vat.termin_platnosci})")
            nadwyzka = res.vat.vat_do_przeniesienia_na_kolejny_okres
        print(f" * Łącznie zobowiązania: {res.suma_wszystkich_zobowiazan:.2f} zł")


def cmd_review(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Przygotowuję zestawienie weryfikacyjne dla {profile.nazwa} za {args.rok}-{args.miesiac.zfill(2)}...")
    review = PreSettlementReview.build(profile, args.rok, args.miesiac)
    print("\n" + review.generate_markdown())


def cmd_simulate(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    stawka = Decimal(str(args.stawka_ryczaltu or (profile.domyslna_stawka_ryczaltu if profile else 0.12)))

    comp = simulate_tax_regimes(
        przychody_roczne=Decimal(str(args.przychod)),
        koszty_roczne=Decimal(str(args.koszty)),
        stawka_ryczaltu=stawka,
        rok=str(args.rok),
    )

    print("\n" + comp.generate_markdown())


def cmd_audit(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Audytuję koszty firmy {profile.nazwa} za {args.rok}-{args.miesiac.zfill(2)}...")
    audit = audit_expense_leaks(profile, args.rok, args.miesiac)

    if audit.liczba_alertow == 0:
        print("✅ Brak wykrytych anomalii lub brakujących regularnych faktur.")
    else:
        print(f"\n⚠️  Wykryto {audit.liczba_alertow} alertów kosztowych:")
        for a in audit.alerty:
            print(f" - [{a.typ}] {a.nazwa_kontrahenta}: {a.opis}")


def cmd_regula(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    from src.skills.cost_classifier import RegulyKosztoweFirmy, KwalifikacjaKosztu
    reguly = RegulyKosztoweFirmy.load(profile)
    kwal = KwalifikacjaKosztu(args.kwalifikacja)
    reguly.dodaj_regule(
        profile=profile,
        wzorzec=args.wzorzec,
        kwalifikacja=kwal,
        uzasadnienie=args.uzasadnienie,
        nip_kontrahenta=args.kontrahent_nip
    )
    print(f"✅ Zapisano regułę kosztową dla firmy {profile.nazwa}:")
    print(f" * Wzorzec: '{args.wzorzec}' -> {kwal.value} ({args.uzasadnienie})")
    if args.kontrahent_nip:
        print(f" * Kontrahent NIP: {args.kontrahent_nip}")
    else:
        print(" * Zasięg: Globalna reguła firmy")


def cmd_set_token(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    profile.set_ksef_token(token=args.token, srodowisko=args.srodowisko)
    print(f"✅ Pomyślnie zapisano token KSeF w profilu firmy!")
    print(f" * Firma: {profile.nazwa} (NIP: {profile.nip})")
    print(f" * Środowisko KSeF: {profile.ksef.srodowisko}")
    print(f" * Ścieżka pliku: firmy/{profile.katalog_nazwa}/profil.json")


def cmd_extract_non_ksef(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
    from src.core.invoice import InvoiceType
    rok_str = str(args.rok)
    miesiac_str = str(args.miesiac).zfill(2)

    typ_filter = None
    if args.typ == "sprzedaz":
        typ_filter = InvoiceType.SPRZEDAZ
    elif args.typ == "koszty":
        typ_filter = InvoiceType.KOSZT

    print(f"Rozpoczynam ekstrakcję dokumentów non-ksef-raw ({args.typ}) dla {profile.nazwa} za {rok_str}-{miesiac_str}...")
    extracted = NonKSeFExtractor.extract_all(profile, rok_str, miesiac_str, typ=typ_filter, force=args.force)
    print(f"✅ Zakończono ekstrakcję non-KSeF! Przetworzono i zaktualizowano {len(extracted)} faktur w non-ksef-extracted/.")
    for p in extracted:
        print(f" * Zapisano: {p.parent.parent.name}/{p.parent.name}/{p.name}")


def main():
    parser = argparse.ArgumentParser(description="TaxPilot AI - Autonomiczny Asystent Podatkowy JDG")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Polecenie sync
    p_sync = subparsers.add_parser("sync", help="Synchronizuj faktury z KSeF za dany miesiąc")
    p_sync.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_sync.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_sync.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_sync.set_defaults(func=cmd_sync)

    # Polecenie sync-zakres
    p_sync_range = subparsers.add_parser("sync-zakres", help="Synchronizuj faktury z KSeF dla zakresu dat (np. wiele miesięcy w 2 zapytaniach)")
    p_sync_range.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_sync_range.add_argument("--od", required=True, help="Data początkowa ISO (np. 2026-05-01)")
    p_sync_range.add_argument("--do", required=True, help="Data końcowa ISO (np. 2026-11-08)")
    p_sync_range.set_defaults(func=cmd_sync_range)

    # Polecenie przeglad (weryfikacja przed rozliczeniem)
    p_rev = subparsers.add_parser("przeglad", aliases=["review"], help="Przegląd dokumentów przed rozliczeniem (przychody, koszty do akceptacji, pozycje do wyjaśnienia)")
    p_rev.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_rev.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_rev.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_rev.set_defaults(func=cmd_review)

    # Polecenie rozlicz
    p_settle = subparsers.add_parser("rozlicz", help="Przeprowadź pełne rozliczenie miesiąca")
    p_settle.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_settle.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_settle.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_settle.add_argument("--nadwyzka-vat", default="0.00", help="Nadwyżka VAT z poprzedniego miesiąca")
    p_settle.set_defaults(func=cmd_settle)

    # Polecenie rozlicz-rok
    p_settle_year = subparsers.add_parser("rozlicz-rok", help="Sekwencyjne rozliczenie wielu miesięcy z przenoszeniem nadwyżek VAT")
    p_settle_year.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_settle_year.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_settle_year.add_argument("--od", default="1", help="Miesiąc początkowy (1-12)")
    p_settle_year.add_argument("--do", default="12", help="Miesiąc końcowy (1-12)")
    p_settle_year.set_defaults(func=cmd_settle_year)

    # Polecenie symulacja
    p_sim = subparsers.add_parser("symulacja", help="Porównaj formy opodatkowania (Ryczałt vs Liniowy vs Skala)")
    p_sim.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_sim.add_argument("--przychod", type=float, required=True, help="Roczny przychód netto w PLN")
    p_sim.add_argument("--koszty", type=float, default=0.0, help="Roczne koszty netto w PLN")
    p_sim.add_argument("--stawka-ryczaltu", type=float, default=None, help="Stawka ryczałtu (np. 0.12 dla IT)")
    p_sim.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_sim.set_defaults(func=cmd_simulate)

    # Polecenie audyt
    p_audit = subparsers.add_parser("audyt", help="Wykryj brakujące faktury kosztowe i anomalie")
    p_audit.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_audit.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_audit.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_audit.set_defaults(func=cmd_audit)

    # Polecenie extract-non-ksef
    p_ext = subparsers.add_parser("extract-non-ksef", help="Ekstrahuj faktury z folderów non-ksef-raw (sprzedaż i koszty) do non-ksef-extracted")
    p_ext.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_ext.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_ext.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_ext.add_argument("--typ", choices=["sprzedaz", "koszty", "all"], default="all", help="Typ faktur do ekstrakcji (sprzedaz, koszty lub all)")
    p_ext.add_argument("--force", action="store_true", help="Wymuś ponowną ekstrakcję nawet jeśli plik już istnieje")
    p_ext.set_defaults(func=cmd_extract_non_ksef)

    # Polecenie regula
    p_reg = subparsers.add_parser("regula", help="Zapisz trwałą regułę kwalifikacji pozycji kosztowej")
    p_reg.add_argument("--nip", default="7770001122", help="NIP firmy")
    p_reg.add_argument("--kontrahent-nip", default=None, help="NIP kontrahenta (opcjonalny)")
    p_reg.add_argument("--wzorzec", required=True, help="Fragment opisu pozycji faktury (np. 'usługi inne', 'tv')")
    p_reg.add_argument("--kwalifikacja", required=True, choices=["FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"], help="Kwalifikacja podatkowa")
    p_reg.add_argument("--uzasadnienie", default="", help="Uzasadnienie podatkowe decyzji")
    p_reg.set_defaults(func=cmd_regula)

    # Polecenie set-token
    p_tok = subparsers.add_parser("set-token", help="Zapisz token KSeF w profilu firmy (firmy/{nazwa}/profil.json)")
    p_tok.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_tok.add_argument("--token", required=True, help="Token autoryzacyjny KSeF")
    p_tok.add_argument("--srodowisko", choices=["TEST", "DEMO", "PROD"], default=None, help="Środowisko KSeF (TEST / DEMO / PROD)")
    p_tok.set_defaults(func=cmd_set_token)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
