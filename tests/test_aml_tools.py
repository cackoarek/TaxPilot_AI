"""
Testy jednostkowe modułu weryfikacji kontrahentów AML, sankcji i rejestrów (src/skills/aml_tools.py).
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

from src.skills.aml_tools import (
    AMLVerificationEngine,
    DecyzjaWspolpracy,
    PoziomRyzykaAML,
    StatusRachunkuBankowego,
    _normalize_name,
    check_sanctions,
)


class TestAMLVerification(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(_normalize_name("Novatek Polska Sp. z o.o."), "novatekpolska")
        self.assertEqual(_normalize_name("Gazprom Export LLC"), "gazpromexport")
        self.assertEqual(_normalize_name("Kowalski Jan Świerk"), "kowalskijanswierk")

    def test_check_sanctions_by_nip(self):
        mswia, ue, hits = check_sanctions("5252877567", "Jakaś Nazwa Sp. z o.o.")
        self.assertTrue(mswia)
        self.assertTrue(ue)
        self.assertGreater(len(hits), 0)

    def test_check_sanctions_by_name(self):
        mswia, ue, hits = check_sanctions("1112223344", "PAO Gazprom Gazociągi")
        self.assertTrue(mswia)
        self.assertTrue(ue)
        self.assertGreater(len(hits), 0)

    def test_check_sanctions_by_person(self):
        mswia, ue, hits = check_sanctions(
            "1112223344",
            "Firma Handlowa XYZ",
            representatives=["Wiaczesław Kantor"],
        )
        self.assertTrue(mswia)
        self.assertTrue(ue)
        self.assertGreater(len(hits), 0)

    def test_clean_contractor_verification(self):
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5250001090",
                "nazwa": "ORANGE POLSKA S.A.",
                "regon": "012100784",
                "adres": "Al. Jerozolimskie 160, 02-326 Warszawa",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["12102010260000123456789012"],
            }
            karta = AMLVerificationEngine.verify_contractor(
                nip="5250001090",
                rachunek_bankowy="PL 12 1020 1026 0000 1234 5678 9012",
                kwota_transakcji=Decimal("5000.00"),
            )

            self.assertEqual(karta.poziom_ryzyka, PoziomRyzykaAML.NISKIE)
            self.assertEqual(karta.decyzja, DecyzjaWspolpracy.AKCEPTACJA)
            self.assertEqual(karta.status_rachunku, StatusRachunkuBankowego.ZGODNY_BIALA_LISTA)
            self.assertFalse(karta.sankcje_mswia)
            self.assertFalse(karta.sankcje_ue)
            self.assertTrue(len(karta.sha256_hash) == 64)

            # Raport Markdown generuje się poprawnie
            md = karta.generate_markdown_card()
            self.assertIn("ORANGE POLSKA S.A.", md)
            self.assertIn("AKCEPTACJA WSPÓŁPRACY I PŁATNOŚCI", md)

    def test_sanctioned_entity_stop_decision(self):
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5252877567",
                "nazwa": "NOVATEK GREEN ENERGY SP. Z O.O.",
                "regon": "123456789",
                "adres": "Warszawa",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": [],
            }
            karta = AMLVerificationEngine.verify_contractor(
                nip="5252877567",
            )

            self.assertEqual(karta.poziom_ryzyka, PoziomRyzykaAML.KRYTYCZNE_STOP)
            self.assertEqual(karta.decyzja, DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP)
            self.assertTrue(karta.sankcje_mswia)
            self.assertTrue(karta.sankcje_ue)

            md = karta.generate_markdown_card()
            self.assertIn("ODMOWA WSPÓŁPRACY – BLOKADA TRANSAKCJI", md)
            self.assertIn("FIGURUJE NA LIŚCIE SANKCYJNEJ", md)

    def test_unregistered_bank_account_warning(self):
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "7770002233",
                "nazwa": "Firma Testowa Sp. z o.o.",
                "regon": "987654321",
                "adres": "Poznań",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["99999999999999999999999999"],
            }
            # Płatność na kwotę 20 000 zł (powyżej progu 15 000 zł) z innym kontem
            karta = AMLVerificationEngine.verify_contractor(
                nip="7770002233",
                rachunek_bankowy="11112222333344445555666677",
                kwota_transakcji=Decimal("20000.00"),
            )

            self.assertEqual(karta.poziom_ryzyka, PoziomRyzykaAML.SREDNIE)
            self.assertEqual(karta.decyzja, DecyzjaWspolpracy.WYMAGA_WYJASNIENIA)
            self.assertEqual(karta.status_rachunku, StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE)
            self.assertIn("Białej Liście Podatników VAT", karta.uzasadnienie_decyzji)

    def test_verification_service_verify_month(self):
        from src.skills.aml_tools import VerificationService
        from tests.fixtures import setup_test_company

        profile = setup_test_company()
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5252545285",
                "nazwa": "Klient Korporacyjny Sp. z o.o.",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": [],
            }
            raport = VerificationService.verify_month(profile, "2026", "04", zapisz_pliki=True)

            self.assertGreater(raport.liczba_kontrahentow, 0)
            self.assertGreaterEqual(raport.liczba_niska, 1)

            # Sprawdzenie utworzenia katalogu i plików w weryfikacje/
            wer_dir = profile.katalog_firmy / "weryfikacje" / "2026" / "04"
            self.assertTrue((wer_dir / "raport-weryfikacji.md").exists())
            self.assertTrue((wer_dir / "raport-weryfikacji.json").exists())
            self.assertTrue((wer_dir / "raport-weryfikacji.pdf").exists())
            self.assertTrue((wer_dir / "karty").exists())

            # Czy pliki w karty/ istnieją (zarówno .md jak i .pdf)
            karty_files = list((wer_dir / "karty").glob("*-karta.md"))
            self.assertGreater(len(karty_files), 0)
            pdf_files = list((wer_dir / "karty").glob("*-karta.pdf"))
            self.assertGreater(len(pdf_files), 0)

    def test_generate_pdf_card_and_report_files(self):
        """Testuje bezpośrednie generowanie plików PDF dla karty i raportu."""
        import tempfile
        from pathlib import Path

        from src.skills.aml_tools import KartaWeryfikacjiKontrahenta, MiesiecznyRaportWeryfikacji
        from tests.fixtures import setup_test_company

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            karta = KartaWeryfikacjiKontrahenta(
                nip="5213242793",
                nazwa="PIOTR WIŚNIEWSKI",
                adres="Korkowa 161A/47, 04-549 Warszawa",
                regon="142780404",
                zweryfikowany_rachunek="PL33114020040000370274135103",
                status_rachunku=StatusRachunkuBankowego.ZGODNY_BIALA_LISTA,
                uzasadnienie_decyzji="Kontrahent w pełni zweryfikowany i bezpieczny.",
            )
            card_pdf = tmp_path / "5213242793-karta.pdf"
            karta.generate_pdf_card(card_pdf)
            self.assertTrue(card_pdf.exists())
            self.assertGreater(card_pdf.stat().st_size, 1000)

            # Test raportu zbiorczego
            profile = setup_test_company()
            raport = MiesiecznyRaportWeryfikacji(
                profil=profile,
                rok="2026",
                miesiac="09",
                karty=[karta],
            )
            report_pdf = tmp_path / "raport-weryfikacji.pdf"
            raport.generate_pdf_report(report_pdf)
            self.assertTrue(report_pdf.exists())
            self.assertGreater(report_pdf.stat().st_size, 1000)

    def test_cache_deduplication_single_api_call(self):
        """Testuje, czy ten sam kontrahent sprawdzany wielokrotnie odpytuje API tylko 1 raz."""
        AMLVerificationEngine.clear_cache()
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5250001090",
                "nazwa": "ORANGE POLSKA S.A.",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["12102010260000123456789012"],
            }
            # 1. Pierwsze sprawdzenie (odpytuje API)
            karta1 = AMLVerificationEngine.verify_contractor(nip="5250001090")
            # 2. Drugie sprawdzenie tego samego kontrahenta (np. kolejna faktura za 10 sek)
            karta2 = AMLVerificationEngine.verify_contractor(nip="5250001090")
            # 3. Trzecie sprawdzenie (np. faktura z kolejnego miesiąca)
            karta3 = AMLVerificationEngine.verify_contractor(nip="5250001090")

            # API zewnętrzne powinno być wywołane dokładnie 1 raz!
            self.assertEqual(mock_mf.call_count, 1)
            self.assertEqual(karta1.sha256_hash, karta2.sha256_hash)
            self.assertEqual(karta2.sha256_hash, karta3.sha256_hash)

    def test_offline_network_failure_handling(self):
        """Testuje, czy błąd sieciowy jest jawnie oznaczany i nie zatruwa cache."""
        AMLVerificationEngine.clear_cache()
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5252545285",
                "status_vat": "Brak połączenia z API MF (błąd sieci / offline)",
                "platnik_vat": False,
                "blad_polaczenia": True,
                "komunikat_bledu": "Connection refused",
            }

            karta = AMLVerificationEngine.verify_contractor(nip="5252545285", nazwa="KAFT SP. Z O.O.")
            self.assertTrue(karta.blad_polaczenia)
            self.assertEqual(karta.poziom_ryzyka, PoziomRyzykaAML.SREDNIE)
            self.assertEqual(karta.decyzja, DecyzjaWspolpracy.WYMAGA_WYJASNIENIA)
            self.assertIn("BRAK DOSTĘPU DO REJESTRÓW MF", karta.uzasadnienie_decyzji)

            md = karta.generate_markdown_card()
            self.assertIn("WERYFIKACJA NIEKOMPLETNA", md)
            self.assertIn("python -m src.cli weryfikuj", md)

            # Sprawdzenie, czy nie zatruło cache - kolejna próba powinna ponownie odpytać API
            _ = AMLVerificationEngine.verify_contractor(nip="5252545285")
            self.assertEqual(mock_mf.call_count, 2)

    def test_monthly_report_offline_warning(self):
        """Testuje, czy zbiorczy raport miesięczny zawiera ostrzeżenie o pozycjach offline."""
        from src.skills.aml_tools import KartaWeryfikacjiKontrahenta, MiesiecznyRaportWeryfikacji
        from tests.fixtures import setup_test_company

        profile = setup_test_company()
        karta_offline = KartaWeryfikacjiKontrahenta(
            nip="5252545285",
            nazwa="KAFT SP. Z O.O.",
            adres=None,
            blad_polaczenia=True,
            komunikat_bledu="Offline test",
            status_vat="Brak połączenia z API MF (błąd sieci / offline)",
            platnik_vat_czynny=False,
            poziom_ryzyka=PoziomRyzykaAML.SREDNIE,
            decyzja=DecyzjaWspolpracy.WYMAGA_WYJASNIENIA,
            uzasadnienie_decyzji="Błąd sieci",
        )
        raport = MiesiecznyRaportWeryfikacji(
            profil=profile,
            rok="2026",
            miesiac="01",
            karty=[karta_offline],
        )

        self.assertEqual(raport.liczba_bledow_sieci, 1)
        md = raport.generate_markdown_report()
        self.assertIn("RAPORT ZAWIERA POZYCJE NIEZWERYFIKOWANE Z POWODU BRAKU SIECI", md)
        self.assertIn("--force", md)

    def test_virtual_bank_account_verification(self):
        """Testuje weryfikację rachunku wirtualnego (subkonta masowych płatności, np. Play) przez endpoint check."""
        with (
            patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf,
            patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.check_bank_account_mf") as mock_check,
        ):
            # Lista ogólna nie zawiera konta wirtualnego
            mock_mf.return_value = {
                "nip": "9512120077",
                "nazwa": "P4 SP. Z O.O.",
                "regon": "015808609",
                "adres": "WYNALAZEK 1, 02-677 WARSZAWA",
                "status_vat": "czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["74109000040000001178980015"],
            }
            # Dedykowany endpoint /api/check/nip/{nip}/bank-account/{acc} potwierdza powiązanie
            mock_check.return_value = {"assigned": True, "request_id": "test-req-123", "blad_polaczenia": False}

            karta = AMLVerificationEngine.verify_contractor(
                nip="9512120077",
                rachunek_bankowy="93109000047777010097655657",
                force=True,
            )

            self.assertEqual(karta.status_rachunku, StatusRachunkuBankowego.ZGODNY_BIALA_LISTA)
            mock_check.assert_called_once()

    def test_foreign_company_verification_amazon(self):
        """Testuje poprawność weryfikacji AML/compliance dla spółki zagranicznej zarejestrowanej do VAT w PL (Amazon)."""
        AMLVerificationEngine.clear_cache()
        with patch("src.level_1_ingestion.company_fetcher.CompanyFetcher.fetch_from_mf_biala_lista") as mock_mf:
            mock_mf.return_value = {
                "nip": "5262907815",
                "nazwa": "AMAZON EU S.A.R.L.",
                "regon": None,
                "krs": None,
                "adres": "AVENUE JOHN F.KENNEDY 38, 1855 LUKSEMBURG",
                "status_vat": "Czynny",
                "platnik_vat": True,
                "rachunki_bankowe": ["66103015080000000819700000"],
                "zrodlo": "MF_BIALA_LISTA",
                "blad_polaczenia": False,
            }
            karta = AMLVerificationEngine.verify_contractor(
                nip="5262907815",
                nazwa="Amazon EU S.a r.l.",
                adres="38 avenue John F. Kennedy, Luksemburg L-1855",
                force=True,
            )

            self.assertEqual(karta.forma_prawna, "SPÓŁKA ZAGRANICZNA (ZAREJESTROWANA DO VAT W POLSCE)")
            self.assertEqual(karta.crbr_status, "NIE_DOTYCZY_ZAGRANICZNA")
            self.assertIn("podmiot zagraniczny", karta.krs.lower())
            self.assertTrue(karta.platnik_vat_czynny)
            self.assertEqual(karta.poziom_ryzyka, PoziomRyzykaAML.NISKIE)
            self.assertEqual(karta.decyzja, DecyzjaWspolpracy.AKCEPTACJA)
            self.assertIn("spółka zagraniczna", karta.uzasadnienie_decyzji.lower())

            # Generowanie Markdown
            md = karta.generate_markdown_card()
            self.assertIn("SPÓŁKA ZAGRANICZNA (ZAREJESTROWANA DO VAT W POLSCE)", md)
            self.assertIn("Nie dotyczy polskiego CRBR", md)
            self.assertIn("Zarząd / Dyrektorzy", md)
            self.assertNotIn("właściciel JDG", md)

            # Generowanie PDF
            import tempfile
            from pathlib import Path

            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / "amazon-karta.pdf"
                karta.generate_pdf_card(pdf_path)
                self.assertTrue(pdf_path.exists())
                self.assertGreater(pdf_path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
