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
import re
from decimal import Decimal
from datetime import datetime

from src.core.company import CompanyProfile, FormaOpodatkowania, ZUSConfig, KSeFConfig, TypZUS
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


def cmd_init_company(args):
    """Inicjalizuje profil nowej firmy, tworzy katalogi oraz reguły podatkowe."""
    from src.level_1_ingestion.company_fetcher import CompanyFetcher
    from src.skills.cost_classifier import RegulyKosztoweFirmy, RegulaPozycji, KwalifikacjaKosztu
    from src.level_2_bookkeeping.ledger import RegulySprzedazyFirmy

    nip_clean = re.sub(r"[^0-9]", "", args.nip)
    if len(nip_clean) != 10:
        print(f"Błąd: Nieprawidłowy NIP ({args.nip}). Polski NIP musi składać się z 10 cyfr.")
        sys.exit(1)

    existing = CompanyProfile.load_by_nip(nip_clean)
    if existing and not args.force:
        print(f"Uwaga: Profil firmy z NIP {nip_clean} już istnieje ({existing.nazwa}).")
        print(f"Ścieżka: {existing.katalog_firmy}")
        print("Użyj flagi --force, jeśli chcesz nadpisać profil.")
        return

    nazwa = args.nazwa
    adres = args.adres
    regon = args.regon
    platnik_vat = not args.zwolniony_z_vat
    kody_pkd = [p.strip().upper() for p in args.pkd.split(",") if p.strip()] if args.pkd else []

    # 1. Automatyczne pobranie danych z rejestrów publicznych
    if not args.no_fetch:
        print(f"🔍 Wyszukiwanie danych firmy w rejestrach publicznych (Biała Lista MF / CEIDG) dla NIP: {nip_clean}...")
        public_data = CompanyFetcher.fetch_company_info(nip_clean, ceidg_token=args.ceidg_token)
        if public_data.get("nazwa") and not nazwa:
            nazwa = public_data["nazwa"]
            print(f" * Pobrano oficjalną nazwę: {nazwa}")
        if public_data.get("adres") and not adres:
            adres = public_data["adres"]
            print(f" * Pobrano adres rejestrowy: {adres}")
        if public_data.get("regon") and not regon:
            regon = public_data["regon"]
            print(f" * Pobrano REGON: {regon}")
        if "platnik_vat" in public_data and not args.zwolniony_z_vat:
            platnik_vat = public_data["platnik_vat"]
            status_txt = "Czynny podatnik VAT" if platnik_vat else "Zwolniony z VAT"
            print(f" * Status VAT w MF: {status_txt}")
        if public_data.get("kody_pkd") and not kody_pkd:
            kody_pkd = public_data["kody_pkd"]
            print(f" * Pobrano kody PKD z CEIDG: {', '.join(kody_pkd)}")

    if not nazwa:
        nazwa = f"Firma {nip_clean}"

    forma = FormaOpodatkowania(args.forma.upper())
    zus_typ = TypZUS(args.zus.upper())
    chorobowe = not args.bez_chorobowego

    profile = CompanyProfile(
        nip=nip_clean,
        nazwa=nazwa,
        forma_opodatkowania=forma,
        domyslna_stawka_ryczaltu=float(args.stawka_ryczaltu),
        platnik_vat=platnik_vat,
        zus=ZUSConfig(typ=zus_typ, chorobowe_dobrowolne=chorobowe),
        ksef=KSeFConfig(srodowisko=args.srodowisko.upper(), token=args.token),
        kody_pkd=kody_pkd,
        regon=regon,
        adres=adres
    )
    profil_path = profile.save()

    # 2. Generowanie wstępnych reguł kosztowych
    reguly = RegulyKosztoweFirmy(nip_firmy=nip_clean)
    reguly.reguly_globalne.append(
        RegulaPozycji(wzorzec="paliwo", kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50, uzasadnienie="Paliwo do pojazdu osobowego (art. 86a ustawy o VAT)")
    )
    is_it = any(code.startswith(("62.", "58.2", "63.")) for code in kody_pkd)
    if is_it or not kody_pkd:
        reguly.reguly_globalne.extend([
            RegulaPozycji(wzorzec="hosting", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Infrastruktura serwerowa i chmurowa"),
            RegulaPozycji(wzorzec="cloud", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Usługi chmurowe"),
            RegulaPozycji(wzorzec="serwer", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Serwery i bazy danych"),
            RegulaPozycji(wzorzec="oprogramowanie", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Licencje na oprogramowanie"),
        ])
    reguly.save(profile)

    # 3. Puste reguły sprzedaży
    reguly_sprz = RegulySprzedazyFirmy(nip_firmy=nip_clean)
    reguly_sprz.save(profile)

    # 4. Inicjalizacja struktury katalogów na faktury i rozliczenia
    rok_akt = str(datetime.now().year)
    for m in range(1, 13):
        m_str = f"{m:02d}"
        for kierunek in ["sprzedaz", "koszty"]:
            for sub in ["ksef", "non-ksef-raw", "non-ksef-extracted"]:
                (profile.katalog_firmy / "faktury" / rok_akt / m_str / kierunek / sub).mkdir(parents=True, exist_ok=True)
    (profile.katalog_firmy / "rozliczenia").mkdir(parents=True, exist_ok=True)

    print("\n🎉 Firma została pomyślnie zainicjowana!")
    print(f" * NIP: {profile.nip}")
    print(f" * Nazwa: {profile.nazwa}")
    print(f" * Adres: {profile.adres or 'Brak'}")
    print(f" * Forma opodatkowania: {profile.forma_opodatkowania.value} (stawka: {profile.domyslna_stawka_ryczaltu*100:.1f}%)")
    print(f" * ZUS: {profile.zus.typ.value} (chorobowe: {'TAK' if profile.zus.chorobowe_dobrowolne else 'NIE'})")
    print(f" * Kody PKD: {', '.join(profile.kody_pkd) if profile.kody_pkd else 'Nie podano'}")
    print(f" * KSeF: Środowisko {profile.ksef.srodowisko}, Token: {'Skonfigurowany ✅' if profile.ksef.token else 'Brak (wymaga uzupełnienia) ⚠️'}")
    print(f" * Katalog firmy: {profile.katalog_firmy}")
    print(f" * Plik profilu: {profil_path}")
    if not profile.ksef.token:
        print("\n💡 Kolejny krok:")
        print(f"   Wygeneruj token w Aplikacji Podatnika KSeF i uruchom:")
        print(f"   python -m src.cli set-token --nip {profile.nip} --token \"<TWOJ_TOKEN>\" --srodowisko {profile.ksef.srodowisko}")


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

    # Polecenie init-firma (onboarding nowego konta)
    p_init = subparsers.add_parser("init-firma", aliases=["init"], help="Zainicjalizuj nowy profil firmy i strukturę katalogów")
    p_init.add_argument("--nip", required=True, help="10-cyfrowy NIP firmy")
    p_init.add_argument("--nazwa", default=None, help="Nazwa firmy (pobrana automatycznie z rejestru jeśli brak)")
    p_init.add_argument("--adres", default=None, help="Adres firmy (pobrany automatycznie z rejestru jeśli brak)")
    p_init.add_argument("--regon", default=None, help="REGON firmy (pobrany automatycznie z rejestru jeśli brak)")
    p_init.add_argument("--forma", default="RYCZALT", choices=["RYCZALT", "LINIOWY", "SKALA"], help="Forma opodatkowania")
    p_init.add_argument("--stawka-ryczaltu", type=float, default=0.12, help="Domyślna stawka ryczałtu (np. 0.12)")
    p_init.add_argument("--zwolniony-z-vat", action="store_true", help="Oznacz, jeśli firma jest zwolniona z VAT")
    p_init.add_argument("--zus", default="PELNY_ZUS", choices=["PELNY_ZUS", "MALY_ZUS_PLUS", "ULGA_NA_START"], help="Schemat składek ZUS")
    p_init.add_argument("--bez-chorobowego", action="store_true", help="Wyłącz dobrowolne ubezpieczenie chorobowe ZUS")
    p_init.add_argument("--pkd", default=None, help="Kody PKD po przecinku (np. '62.01.Z,62.02.Z')")
    p_init.add_argument("--token", default=None, help="Token autoryzacyjny KSeF")
    p_init.add_argument("--srodowisko", default="PROD", choices=["TEST", "DEMO", "PROD"], help="Środowisko KSeF")
    p_init.add_argument("--no-fetch", action="store_true", help="Pomiń pobieranie danych z rejestrów publicznych online")
    p_init.add_argument("--ceidg-token", default=None, help="Opcjonalny token API CEIDG (dane.biznes.gov.pl)")
    p_init.add_argument("--force", action="store_true", help="Nadpisz profil jeśli już istnieje")
    p_init.set_defaults(func=cmd_init_company)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
