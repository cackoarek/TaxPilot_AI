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
from pathlib import Path

from src.core.company import CompanyProfile
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_3_tax_settlement.settlement_service import SettlementService
from src.skills.pre_settlement_review import PreSettlementReview
from src.skills.tax_advisor_tools import audit_expense_leaks, simulate_tax_regimes


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
    print(
        f"Rozpoczynam synchronizację zakresu {args.od} do {args.do} z KSeF ({profile.ksef.srodowisko}) dla {profile.nazwa}..."
    )
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

    target_dir = profile.katalog_firmy / "rozliczenia" / str(args.rok) / str(args.miesiac).zfill(2)
    if result.ledger.duplikaty:
        print(f"\n⚠️  UWAGA: Wykryto i bezpiecznie wykluczono {len(result.ledger.duplikaty)} zdublowanych dokumentów!")
        for d in result.ledger.duplikaty:
            print(
                f"    - [{d.typ_duplikatu.value}] {d.faktura_odrzucona.numer} ({d.plik_zrodlowy_odrzucony}): {d.rekomendacja}"
            )

    print("\n📂 Wygenerowane raporty archiwalne:")
    print(f" * Paczka Przelewów i Podsumowanie: {target_dir / 'rozliczenie.md'}")
    print(f" * Ewidencja Przychodów (miesiąc):  {target_dir / 'ewidencja-przychodow.md'}")
    print(f" * Ewidencja Przychodów - Sumy YTD: {target_dir / 'ewidencja-przychodow-sumy.md'}")
    print(f" * Sprawozdanie i Audyt Podatkowy:  {target_dir / 'sprawozdanie.md'}")
    print(f" * Stan maszynowy JSON:             {target_dir / 'rozliczenie.json'}")

    wer_dir = profile.katalog_firmy / "weryfikacje" / str(args.rok) / str(args.miesiac).zfill(2)
    if (wer_dir / "raport-weryfikacji.md").exists():
        print(f" * Raport Weryfikacji (AML / Sankcje): {wer_dir / 'raport-weryfikacji.md'}")


def cmd_settle_year(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    import shutil

    if getattr(args, "clean", False):
        target_year_dir = profile.katalog_firmy / "rozliczenia" / str(args.rok)
        if target_year_dir.exists():
            print(f"🧹 Usuwam dotychczasowe rozliczenia w {target_year_dir}...")
            shutil.rmtree(target_year_dir)
            target_year_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Rozpoczynam sekwencyjne rozliczenie roku {args.rok} (od {args.od} do {args.do}) dla firmy: {profile.nazwa}..."
    )
    nadwyzka = Decimal("0.00")
    start_m = int(args.od)
    end_m = int(args.do)

    for m in range(start_m, end_m + 1):
        m_str = f"{m:02d}"
        res = SettlementService.settle_month(
            profile=profile, rok=str(args.rok), miesiac=m_str, nadwyzka_vat_poprzedni=nadwyzka, zapisz_raporty=True
        )
        print(f"\n--- Zaksięgowano miesiąc {args.rok}-{m_str} ---")
        print(
            f" * Przychód: {res.ledger.ewidencja_przychodow.laczny_przychod_netto:.2f} zł (narastająco: {res.przychod_roczny_narastajaco:.2f} zł)"
        )
        print(f" * ZUS: {res.zus.lacznie_do_zaplaty:.2f} zł (termin: {res.zus.termin_platnosci})")
        if res.pit28:
            print(f" * PIT-28 (12%): {res.pit28.zaliczka_pit28_zaokraglona} zł (termin: {res.pit28.termin_platnosci})")
        if res.vat:
            print(
                f" * VAT do zapłaty: {res.vat.vat_do_zaplaty_zaokraglony} zł (przeniesienie nadwyżki: {res.vat.vat_do_przeniesienia_na_kolejny_okres:.2f} zł, termin: {res.vat.termin_platnosci})"
            )
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

    from src.skills.cost_classifier import KwalifikacjaKosztu, RegulyKosztoweFirmy

    reguly = RegulyKosztoweFirmy.load(profile)
    kwal = KwalifikacjaKosztu(args.kwalifikacja)
    reguly.dodaj_regule(
        profile=profile,
        wzorzec=args.wzorzec,
        kwalifikacja=kwal,
        uzasadnienie=args.uzasadnienie,
        nip_kontrahenta=args.kontrahent_nip,
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

    profile.set_ksef_token(token=args.token, srodowisko=args.srodowisko, auth_type="token")
    print("✅ Pomyślnie zapisano token KSeF w profilu firmy!")
    print(f" * Firma: {profile.nazwa} (NIP: {profile.nip})")
    print(f" * Środowisko KSeF: {profile.ksef.srodowisko}")
    print(f" * Ścieżka pliku: firmy/{profile.katalog_nazwa}/profil.json")


def cmd_set_certs(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    auth_cert_p = Path(args.auth_cert) if args.auth_cert else None
    auth_key_p = Path(args.auth_key) if args.auth_key else None
    off_cert_p = Path(args.offline_cert) if args.offline_cert else None
    off_key_p = Path(args.offline_key) if args.offline_key else None

    auth_cert_b = auth_cert_p.read_bytes() if auth_cert_p and auth_cert_p.exists() else None
    auth_key_b = auth_key_p.read_bytes() if auth_key_p and auth_key_p.exists() else None
    off_cert_b = off_cert_p.read_bytes() if off_cert_p and off_cert_p.exists() else None
    off_key_b = off_key_p.read_bytes() if off_key_p and off_key_p.exists() else None

    profile.set_ksef_certificates(
        auth_cert_bytes=auth_cert_b,
        auth_key_bytes=auth_key_b,
        auth_password=args.auth_password,
        offline_cert_bytes=off_cert_b,
        offline_key_bytes=off_key_b,
        offline_password=args.offline_password,
        auth_type="certyfikat",
        srodowisko=args.srodowisko,
    )
    print("✅ Pomyślnie wgrano i skonfigurowano certyfikaty KSeF w profilu firmy!")
    print(f" * Firma: {profile.nazwa} (NIP: {profile.nip})")
    print(f" * Katalog certyfikatów: firmy/{profile.katalog_nazwa}/certyfikaty/")
    print(f" * Aktywna metoda autoryzacji: {profile.ksef.auth_type} (XAdES-BES)")
    print(f" * Środowisko KSeF: {profile.ksef.srodowisko}")


def cmd_extract_non_ksef(args):
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    from src.core.invoice import InvoiceType
    from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor

    rok_str = str(args.rok)
    miesiac_str = str(args.miesiac).zfill(2)

    typ_filter = None
    if args.typ == "sprzedaz":
        typ_filter = InvoiceType.SPRZEDAZ
    elif args.typ == "koszty":
        typ_filter = InvoiceType.KOSZT

    print(
        f"Rozpoczynam ekstrakcję dokumentów non-ksef-raw ({args.typ}) dla {profile.nazwa} za {rok_str}-{miesiac_str}..."
    )
    use_ai = getattr(args, "ai", False)
    if use_ai:
        from src.level_1_ingestion.ai_document_extractor import AIDocumentExtractor

        print("🤖 Uruchamiam zaawansowaną ekstrakcję multimodalną przez agenta AI...")
        invoices = AIDocumentExtractor.extract_unprocessed(profile, rok_str, miesiac_str)
        print(f"✅ Zakończono ekstrakcję AI! Odczytano i zaktualizowano {len(invoices)} faktur w non-ksef-extracted/.")
        for inv in invoices:
            print(
                f" * Zapisano: {inv.typ.value}/non-ksef-extracted/{Path(inv.plik_zrodlowy or inv.numer).stem}.json ({inv.suma_brutto} {inv.waluta})"
            )
        return

    extracted = NonKSeFExtractor.extract_all(profile, rok_str, miesiac_str, typ=typ_filter, force=args.force)
    print(
        f"✅ Zakończono ekstrakcję non-KSeF! Przetworzono i zaktualizowano {len(extracted)} faktur w non-ksef-extracted/."
    )
    for p in extracted:
        print(f" * Zapisano: {p.parent.parent.name}/{p.parent.name}/{p.name}")


def cmd_extract_ai(args):
    """Uruchamia ekstrakcję dokumentów graficznych i nieprzetworzonych za pomocą AI."""
    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    from src.level_1_ingestion.ai_document_extractor import AIDocumentExtractor

    rok_str = str(args.rok)
    miesiac_str = str(args.miesiac).zfill(2)

    print(f"🤖 Uruchamiam ekstrakcję AI nieodczytanych faktur dla {profile.nazwa} za {rok_str}-{miesiac_str}...")
    invoices = AIDocumentExtractor.extract_unprocessed(profile, rok_str, miesiac_str)
    print(f"✅ Zakończono ekstrakcję AI! Pomyślnie przetworzono {len(invoices)} dokumentów.")
    for inv in invoices:
        print(
            f" * Zapisano: {inv.typ.value}/non-ksef-extracted/{Path(inv.plik_zrodlowy or inv.numer).stem}.json: {inv.sprzedawca.nazwa} -> {inv.suma_brutto} {inv.waluta}"
        )


def cmd_weryfikuj(args):
    """Weryfikuje pojedynczego kontrahenta (ad-hoc) pod kątem AML, sankcji i Białej Listy."""
    from src.skills.aml_tools import AMLVerificationEngine

    profile = None
    if getattr(args, "firma", None):
        profile = CompanyProfile.load_by_nip(args.firma)

    kwota = Decimal(str(args.kwota)) if getattr(args, "kwota", None) else None
    print(f"Rozpoczynam weryfikację kontrahenta NIP: {args.kontrahent_nip}...")
    karta = AMLVerificationEngine.verify_contractor(
        nip=args.kontrahent_nip,
        nazwa=getattr(args, "nazwa", None),
        rachunek_bankowy=getattr(args, "konto", None),
        kwota_transakcji=kwota,
        profile=profile,
        force=getattr(args, "force", False),
    )

    print("\n" + karta.generate_markdown_card())

    if karta.blad_polaczenia:
        print("\n" + "=" * 80)
        print("⚠️  OSTRZEŻENIE: Brak połączenia z API Białej Listy MF (błąd sieci / tryb offline)!")
        print(f"   Szczegóły: {karta.komunikat_bledu or 'brak odpowiedzi z serwera MF'}")
        print("   Weryfikacja podmiotu jest NIEKOMPLETNA i nie może zostać zatwierdzona w tym stanie.")
        print("👉 Propozycja: Ponów weryfikację w środowisku z dostępem do Internetu:")
        print(f"   python -m src.cli weryfikuj --kontrahent-nip {karta.nip} --force")
        print("=" * 80 + "\n")

    if profile and getattr(args, "rok", None) and getattr(args, "miesiac", None):
        rok_str = str(args.rok)
        miesiac_str = str(args.miesiac).zfill(2)
        target_dir = profile.katalog_firmy / "weryfikacje" / rok_str / miesiac_str / "karty"
        target_dir.mkdir(parents=True, exist_ok=True)
        md_file = target_dir / f"{karta.nip}-karta.md"
        json_file = target_dir / f"{karta.nip}-raw.json"
        pdf_file = target_dir / f"{karta.nip}-karta.pdf"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(karta.generate_markdown_card())
        import json

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(karta.to_dict(), f, indent=2, ensure_ascii=False)
        try:
            karta.generate_pdf_card(pdf_file)
        except Exception:
            pass
        print(f"\n📂 Zapisano kartę weryfikacji w: {md_file} oraz {pdf_file}")


def cmd_weryfikuj_miesiac(args):
    """Weryfikuje wszystkich kontrahentów z faktur miesiąca pod kątem AML, sankcji i Białej Listy."""
    from src.skills.aml_tools import VerificationService

    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Rozpoczynam weryfikację kontrahentów dla {profile.nazwa} za {args.rok}-{args.miesiac.zfill(2)}...")
    raport = VerificationService.verify_month(
        profile, args.rok, args.miesiac, zapisz_pliki=True, force=getattr(args, "force", False)
    )
    print("\n" + raport.generate_markdown_report())

    target_dir = profile.katalog_firmy / "weryfikacje" / str(args.rok) / str(args.miesiac).zfill(2)
    print(f"\n📂 Zapisano kompletny pakiet weryfikacji w: {target_dir}")
    print(f" * Raport zbiorczy Markdown: {target_dir / 'raport-weryfikacji.md'}")
    print(f" * Raport zbiorczy PDF:      {target_dir / 'raport-weryfikacji.pdf'}")
    print(f" * Raport maszynowy JSON:    {target_dir / 'raport-weryfikacji.json'}")
    print(f" * Indywidualne karty ({raport.liczba_kontrahentow} szt. MD + PDF + JSON): {target_dir / 'karty'}")

    if raport.liczba_bledow_sieci > 0:
        print("\n" + "=" * 80)
        print(
            f"⚠️  OSTRZEŻENIE: Wykryto brak połączenia z API rejestrów MF dla {raport.liczba_bledow_sieci} kontrahentów!"
        )
        print("   Zbiorczy raport compliance jest NIEKOMPLETNY i nie powinien być zatwierdzany w tym stanie.")
        print("👉 Propozycja: Uruchom ponowną weryfikację w środowisku z dostępem do Internetu:")
        print(
            f"   python -m src.cli weryfikuj-miesiac --nip {args.nip} --rok {args.rok} --miesiac {args.miesiac} --force"
        )
        print("=" * 80 + "\n")


def cmd_init_company(args):
    """Inicjalizuje profil nowej firmy, tworzy katalogi oraz reguły podatkowe."""
    from src.core.company import initialize_company
    from src.core.validators import clean_nip, validate_nip

    nip_clean = clean_nip(args.nip)
    is_valid, err_msg = validate_nip(nip_clean)
    if not is_valid:
        print(f"Błąd: Nieprawidłowy NIP ({args.nip}): {err_msg}")
        sys.exit(1)

    existing = CompanyProfile.load_by_nip(nip_clean)
    if existing and not args.force:
        print(f"Uwaga: Profil firmy z NIP {nip_clean} już istnieje ({existing.nazwa}).")
        print(f"Ścieżka: {existing.katalog_firmy}")
        print("Użyj flagi --force, jeśli chcesz nadpisać profil.")
        return

    pkd_list = [p.strip().upper() for p in args.pkd.split(",") if p.strip()] if args.pkd else []

    try:
        profile = initialize_company(
            nip=nip_clean,
            nazwa=args.nazwa,
            adres=args.adres,
            regon=args.regon,
            forma_opodatkowania=args.forma.upper(),
            domyslna_stawka_ryczaltu=float(args.stawka_ryczaltu),
            platnik_vat=not args.zwolniony_z_vat,
            zus_typ=args.zus.upper(),
            chorobowe_dobrowolne=not args.bez_chorobowego,
            kody_pkd=pkd_list,
            srodowisko_ksef=args.srodowisko.upper(),
            token_ksef=args.token,
            auto_fetch=not args.no_fetch,
            ceidg_token=args.ceidg_token,
            force=args.force,
        )
        print(f"✅ Pomyślnie utworzono profil firmy: {profile.nazwa} (NIP: {profile.nip})")
        print(f"📁 Ścieżka katalogu: {profile.katalog_firmy}")
        print(f"📄 Profil zapisany: {profile.katalog_firmy / 'profil.json'}")
    except ValueError as e:
        print(f"Błąd inicjalizacji: {e}")

    print("\n🎉 Firma została pomyślnie zainicjowana!")
    print(f" * NIP: {profile.nip}")
    print(f" * Nazwa: {profile.nazwa}")
    print(f" * Adres: {profile.adres or 'Brak'}")
    print(
        f" * Forma opodatkowania: {profile.forma_opodatkowania.value} (stawka: {profile.domyslna_stawka_ryczaltu * 100:.1f}%)"
    )
    print(f" * ZUS: {profile.zus.typ.value} (chorobowe: {'TAK' if profile.zus.chorobowe_dobrowolne else 'NIE'})")
    print(f" * Kody PKD: {', '.join(profile.kody_pkd) if profile.kody_pkd else 'Nie podano'}")
    print(
        f" * KSeF: Środowisko {profile.ksef.srodowisko}, Token: {'Skonfigurowany ✅' if profile.ksef.token else 'Brak (wymaga uzupełnienia) ⚠️'}"
    )
    print(f" * Katalog firmy: {profile.katalog_firmy}")
    print(f" * Plik profilu: {profile.katalog_firmy / 'profil.json'}")
    if not profile.ksef.token:
        print("\n💡 Kolejny krok:")
        print("   Wygeneruj token w Aplikacji Podatnika KSeF i uruchom:")
        print(
            f'   python -m src.cli set-token --nip {profile.nip} --token "<TWOJ_TOKEN>" --srodowisko {profile.ksef.srodowisko}'
        )


def cmd_web(args):
    import uvicorn

    host = args.host or "127.0.0.1"
    port = args.port or 8000
    reload = args.reload
    print("🚀 Uruchamianie TaxPilot AI Web UI...")
    print(f"📍 Adres: http://{host}:{port}")
    uvicorn.run("src.web.app:app", host=host, port=port, reload=reload)


def cmd_agregat_vat(args):
    """Agreguje odliczenia podatku VAT wg kategorii podatkowych i branżowych."""
    from src.skills.vat_aggregator import VATAggregator

    profile = CompanyProfile.load_by_nip(args.nip)
    nip_val = profile.nip if profile else args.nip
    rok_val = str(args.rok)
    miesiace_val = [m.strip().zfill(2) for m in args.miesiace.split(",")] if getattr(args, "miesiace", None) else None

    rep = VATAggregator.aggregate("firmy", nip_val, rok=rok_val, miesiace=miesiace_val)
    print("\n" + rep.to_markdown())

    if getattr(args, "zapisz", False) and profile:
        out_dir = profile.katalog_firmy / "rozliczenia" / rok_val
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "agregat-vat.md"
        json_path = out_dir / "agregat-vat.json"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(rep.to_markdown())
        import json

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(rep.to_dict(), f, indent=2, ensure_ascii=False)
        print("\n📂 Zapisano raport agregacji VAT w:")
        print(f" * {md_path}")
        print(f" * {json_path}")


def cmd_backup(args):
    """Tworzy bezpieczną kopię zapasową danych firmy (OPS-1)."""
    from src.core.backup import create_company_backup

    profile = CompanyProfile.load_by_nip(args.nip)
    if not profile:
        print(f"Błąd: Nie znaleziono profilu firmy dla NIP: {args.nip}")
        sys.exit(1)

    print(f"Tworzę kopię zapasową danych firmy {profile.nazwa} (NIP: {profile.nip})...")
    output_dir = Path(args.output) if args.output else None
    archive_path, sha256_path = create_company_backup(profile, output_dir=output_dir)
    print("\n✅ Kopia zapasowa utworzona pomyślnie!")
    print(f" * Archiwum:     {archive_path}")
    print(f" * Rozmiar:      {archive_path.stat().st_size:,} bajtów")
    print(f" * Suma SHA-256: {sha256_path}")


def cmd_restore(args):
    """Przywraca dane firmy z archiwum kopii zapasowej (OPS-1)."""
    from src.core.backup import restore_company_backup

    archive_path = Path(args.archive)
    if not archive_path.exists():
        print(f"Błąd: Plik archiwum nie istnieje: {archive_path}")
        sys.exit(1)

    print(f"Weryfikacja i przywracanie kopii zapasowej z {archive_path}...")
    try:
        target_dir = Path(args.target_dir) if args.target_dir else None
        no_verify = getattr(args, "no_verify_sha", False)
        profile = restore_company_backup(archive_path, target_base_dir=target_dir, verify_sha=not no_verify)
        print("\n✅ Kopia zapasowa przywrócona pomyślnie!")
        print(f" * Firma:   {profile.nazwa}")
        print(f" * NIP:     {profile.nip}")
        print(f" * Katalog: {profile.katalog_firmy}")
    except Exception as e:
        print(f"\n❌ Błąd podczas przywracania kopii zapasowej: {e}")
        sys.exit(1)


def main():
    from src.version import get_display_version

    app_ver = get_display_version()

    parser = argparse.ArgumentParser(description=f"TaxPilot AI ({app_ver}) - Autonomiczny Asystent Podatkowy JDG")
    parser.add_argument(
        "--version",
        action="version",
        version=f"TaxPilot AI {app_ver}",
        help="Pokaż wersję aplikacji i zakończ",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Polecenie version (wersja aplikacji)
    p_ver = subparsers.add_parser("version", help="Wyświetl wersję aplikacji")
    p_ver.set_defaults(func=lambda args: print(f"TaxPilot AI {get_display_version()}"))

    # Polecenie web (interfejs webowy)
    p_web = subparsers.add_parser(
        "web", aliases=["serve", "gui"], help="Uruchom interfejs webowy (FastAPI + Jinja2 + HTMX)"
    )
    p_web.add_argument("--host", default="127.0.0.1", help="Host (domyślnie 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="Port (domyślnie 8000)")
    p_web.add_argument("--no-reload", dest="reload", action="store_false", help="Wyłącz auto-reload")
    p_web.set_defaults(func=cmd_web, reload=True)

    # Polecenie sync
    p_sync = subparsers.add_parser("sync", help="Synchronizuj faktury z KSeF za dany miesiąc")
    p_sync.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_sync.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_sync.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_sync.set_defaults(func=cmd_sync)

    # Polecenie sync-zakres
    p_sync_range = subparsers.add_parser(
        "sync-zakres", help="Synchronizuj faktury z KSeF dla zakresu dat (np. wiele miesięcy w 2 zapytaniach)"
    )
    p_sync_range.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_sync_range.add_argument("--od", required=True, help="Data początkowa ISO (np. 2026-05-01)")
    p_sync_range.add_argument("--do", required=True, help="Data końcowa ISO (np. 2026-11-08)")
    p_sync_range.set_defaults(func=cmd_sync_range)

    # Polecenie przeglad (weryfikacja przed rozliczeniem)
    p_rev = subparsers.add_parser(
        "przeglad",
        aliases=["review"],
        help="Przegląd dokumentów przed rozliczeniem (przychody, koszty do akceptacji, pozycje do wyjaśnienia)",
    )
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
    p_settle_year = subparsers.add_parser(
        "rozlicz-rok", help="Sekwencyjne rozliczenie wielu miesięcy z przenoszeniem nadwyżek VAT"
    )
    p_settle_year.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_settle_year.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_settle_year.add_argument("--od", default="1", help="Miesiąc początkowy (1-12)")
    p_settle_year.add_argument("--do", default="12", help="Miesiąc końcowy (1-12)")
    p_settle_year.add_argument("--clean", action="store_true", help="Usuń istniejące rozliczenia i przelicz od nowa")
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
    p_ext = subparsers.add_parser(
        "extract-non-ksef", help="Ekstrahuj faktury z folderów non-ksef-raw (sprzedaż i koszty) do non-ksef-extracted"
    )
    p_ext.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_ext.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_ext.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_ext.add_argument(
        "--typ",
        choices=["sprzedaz", "koszty", "all"],
        default="all",
        help="Typ faktur do ekstrakcji (sprzedaz, koszty lub all)",
    )
    p_ext.add_argument("--force", action="store_true", help="Wymuś ponowną ekstrakcję nawet jeśli plik już istnieje")
    p_ext.add_argument(
        "--ai", action="store_true", help="Wymuś zaawansowaną analizę i ekstrakcję przez agenta AI (Vision / OCR)"
    )
    p_ext.set_defaults(func=cmd_extract_non_ksef)

    # Polecenie extract-ai (dedykowana ekstrakcja przez agenta AI)
    p_ext_ai = subparsers.add_parser(
        "extract-ai", help="Wyciągnij dane z nieodczytanych faktur i paragonów przez agenta AI (Vision & OCR)"
    )
    p_ext_ai.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_ext_ai.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_ext_ai.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_ext_ai.set_defaults(func=cmd_extract_ai)

    # Polecenie regula
    p_reg = subparsers.add_parser("regula", help="Zapisz trwałą regułę kwalifikacji pozycji kosztowej")
    p_reg.add_argument("--nip", default="7770001122", help="NIP firmy")
    p_reg.add_argument("--kontrahent-nip", default=None, help="NIP kontrahenta (opcjonalny)")
    p_reg.add_argument("--wzorzec", required=True, help="Fragment opisu pozycji faktury (np. 'usługi inne', 'tv')")
    p_reg.add_argument(
        "--kwalifikacja",
        required=True,
        choices=["FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"],
        help="Kwalifikacja podatkowa",
    )
    p_reg.add_argument("--uzasadnienie", default="", help="Uzasadnienie podatkowe decyzji")
    p_reg.set_defaults(func=cmd_regula)

    # Polecenie set-token
    p_tok = subparsers.add_parser("set-token", help="Zapisz token KSeF w profilu firmy (firmy/{nazwa}/profil.json)")
    p_tok.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_tok.add_argument("--token", required=True, help="Token autoryzacyjny KSeF")
    p_tok.add_argument("--srodowisko", choices=["TEST", "PROD"], default=None, help="Środowisko KSeF (TEST / PROD)")
    p_tok.set_defaults(func=cmd_set_token)

    # Polecenie set-certs (certyfikaty KSeF .crt + .key)
    p_certs = subparsers.add_parser("set-certs", help="Wgraj certyfikaty i klucze KSeF (.crt + .key) do profilu firmy")
    p_certs.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_certs.add_argument("--auth-cert", default=None, help="Ścieżka do pliku certyfikatu uwierzytelnienia (auth.crt)")
    p_certs.add_argument(
        "--auth-key", default=None, help="Ścieżka do pliku klucza prywatnego uwierzytelnienia (auth.key)"
    )
    p_certs.add_argument("--auth-password", default=None, help="Opcjonalne hasło do klucza uwierzytelnienia")
    p_certs.add_argument(
        "--offline-cert", default=None, help="Ścieżka do pliku certyfikatu trybu offline (offline.crt)"
    )
    p_certs.add_argument("--offline-key", default=None, help="Ścieżka do pliku klucza trybu offline (offline.key)")
    p_certs.add_argument("--offline-password", default=None, help="Opcjonalne hasło do klucza trybu offline")
    p_certs.add_argument("--srodowisko", choices=["TEST", "PROD"], default=None, help="Środowisko KSeF (TEST / PROD)")
    p_certs.set_defaults(func=cmd_set_certs)

    # Polecenie init-firma (onboarding nowego konta)
    p_init = subparsers.add_parser(
        "init-firma", aliases=["init"], help="Zainicjalizuj nowy profil firmy i strukturę katalogów"
    )
    p_init.add_argument("--nip", required=True, help="10-cyfrowy NIP firmy")
    p_init.add_argument("--nazwa", default=None, help="Nazwa firmy (pobrana automatycznie z rejestru jeśli brak)")
    p_init.add_argument("--adres", default=None, help="Adres firmy (pobrany automatycznie z rejestru jeśli brak)")
    p_init.add_argument("--regon", default=None, help="REGON firmy (pobrany automatycznie z rejestru jeśli brak)")
    p_init.add_argument(
        "--forma", default="RYCZALT", choices=["RYCZALT", "LINIOWY", "SKALA"], help="Forma opodatkowania"
    )
    p_init.add_argument("--stawka-ryczaltu", type=float, default=0.12, help="Domyślna stawka ryczałtu (np. 0.12)")
    p_init.add_argument("--zwolniony-z-vat", action="store_true", help="Oznacz, jeśli firma jest zwolniona z VAT")
    p_init.add_argument(
        "--zus",
        default="PELNY_ZUS",
        choices=["PELNY_ZUS", "MALY_ZUS_PLUS", "ULGA_NA_START", "TYLKO_ZDROWOTNA"],
        help="Schemat składek ZUS",
    )
    p_init.add_argument("--bez-chorobowego", action="store_true", help="Wyłącz dobrowolne ubezpieczenie chorobowe ZUS")
    p_init.add_argument("--pkd", default=None, help="Kody PKD po przecinku (np. '62.01.Z,62.02.Z')")
    p_init.add_argument("--token", default=None, help="Token autoryzacyjny KSeF")
    p_init.add_argument("--srodowisko", default="PROD", choices=["TEST", "PROD"], help="Środowisko KSeF")
    p_init.add_argument(
        "--no-fetch", action="store_true", help="Pomiń pobieranie danych z rejestrów publicznych online"
    )
    p_init.add_argument("--ceidg-token", default=None, help="Opcjonalny token API CEIDG (dane.biznes.gov.pl)")
    p_init.add_argument("--force", action="store_true", help="Nadpisz profil jeśli już istnieje")
    p_init.set_defaults(func=cmd_init_company)

    # Polecenie weryfikuj (ad-hoc weryfikacja kontrahenta AML / Sankcje / Biała Lista)
    p_wer = subparsers.add_parser(
        "weryfikuj", help="Zweryfikuj kontrahenta pod kątem AML, sankcji MSWiA/UE i Białej Listy VAT"
    )
    p_wer.add_argument("--kontrahent-nip", required=True, help="NIP sprawdzanego kontrahenta")
    p_wer.add_argument("--nazwa", default=None, help="Opcjonalna nazwa kontrahenta")
    p_wer.add_argument("--konto", default=None, help="Numer konta bankowego do weryfikacji na Białej Liście")
    p_wer.add_argument("--kwota", default=None, help="Kwota transakcji (brutto w PLN)")
    p_wer.add_argument("--firma", default="7770001122", help="NIP firmy zlecającej weryfikację")
    p_wer.add_argument("--rok", default=None, help="Rok do zapisu w weryfikacje/{ROK}/{MIESIAC}/karty/")
    p_wer.add_argument("--miesiac", default=None, help="Miesiąc do zapisu")
    p_wer.add_argument("--force", action="store_true", help="Wymuś świeże zapytanie z pominięciem cache")
    p_wer.set_defaults(func=cmd_weryfikuj)

    # Polecenie weryfikuj-miesiac (zbiorcza weryfikacja wszystkich kontrahentów z miesiąca)
    p_wer_m = subparsers.add_parser(
        "weryfikuj-miesiac", help="Zbiorcza weryfikacja kontrahentów ze wszystkich faktur danego miesiąca"
    )
    p_wer_m.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_wer_m.add_argument("--rok", default="2026", help="Rok podatkowy")
    p_wer_m.add_argument("--miesiac", required=True, help="Miesiąc (01-12)")
    p_wer_m.add_argument(
        "--force", action="store_true", help="Wymuś świeże odpytanie API rejestrów z pominięciem cache"
    )
    p_wer_m.set_defaults(func=cmd_weryfikuj_miesiac)

    # Polecenie agregat-vat
    p_vat_agg = subparsers.add_parser(
        "agregat-vat",
        aliases=["vat-kategorie", "vat-sumy"],
        help="Agregacja odliczeń podatku VAT wg kategorii podatkowych i branżowych",
    )
    p_vat_agg.add_argument("--nip", default="7770001122", help="NIP rozliczanej firmy")
    p_vat_agg.add_argument("--rok", default="2026", help="Rok podatkowy (domyślnie 2026)")
    p_vat_agg.add_argument("--miesiace", help="Opcjonalna lista miesięcy oddzielonych przecinkami (np. 01,02,03)")
    p_vat_agg.add_argument(
        "--zapisz", action="store_true", help="Zapisz raport agregacji do rozliczenia/{rok}/agregat-vat.md i .json"
    )
    p_vat_agg.set_defaults(func=cmd_agregat_vat)

    # Polecenie backup (tworzenie kopii zapasowej firmy)
    p_backup = subparsers.add_parser(
        "backup", help="Utwórz bezpieczną kopię zapasową danych firmy (archiwum .tar.gz z SHA-256)"
    )
    p_backup.add_argument("--nip", default="7770001122", help="NIP firmy do wykonania kopii zapasowej")
    p_backup.add_argument("--output", "-o", default=None, help="Katalog docelowy dla kopii zapasowej")
    p_backup.set_defaults(func=cmd_backup)

    # Polecenie restore (przywracanie danych firmy z kopii zapasowej)
    p_restore = subparsers.add_parser(
        "restore", help="Przywróć dane firmy z archiwalnej kopii zapasowej (.tar.gz)"
    )
    p_restore.add_argument("archive", help="Ścieżka do pliku archiwum .tar.gz")
    p_restore.add_argument(
        "--target-dir", default=None, help="Katalog bazowy dla przywracanej firmy (domyślnie katalog firmy/)"
    )
    p_restore.add_argument(
        "--no-verify-sha", action="store_true", help="Pomiń weryfikację sumy kontrolnej SHA-256"
    )
    p_restore.set_defaults(func=cmd_restore)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
