"""
Testy jednostkowe silnika rozliczeń podatkowych (SettlementService, BookkeepingService, ZUS, PIT-28, VAT).
"""

import unittest
from decimal import Decimal

from src.core.company import CompanyProfile
from src.level_3_tax_settlement.settlement_service import SettlementService
from tests.fixtures import cleanup_test_company, setup_isolated_test_company


class TestSettlementService(unittest.TestCase):
    def setUp(self):
        self.profile = setup_isolated_test_company()
        self.assertIsNotNone(self.profile)

    def tearDown(self):
        cleanup_test_company(self.profile)

    def test_settle_april_2026(self):
        # Rozliczenie kwietnia z uwzględnieniem nadwyżki VAT z poprzednich miesięcy
        result = SettlementService.settle_month(
            self.profile, "2026", "04", nadwyzka_vat_poprzedni=Decimal("217.10"), zapisz_raporty=False
        )

        self.assertEqual(result.rok, "2026")
        self.assertEqual(result.miesiac, "04")

        # 2 faktury sprzedaży
        self.assertEqual(len(result.ledger.ewidencja_przychodow.wpisy), 2)
        self.assertEqual(result.ledger.ewidencja_przychodow.laczny_przychod_netto, Decimal("38969.00"))

        # ZUS
        self.assertEqual(result.zus.podstawa_spoleczne, Decimal("5652.00"))
        self.assertEqual(result.zus.suma_spoleczne, Decimal("1926.76"))
        self.assertEqual(result.zus.spoleczne_odliczalne, Decimal("1788.29"))
        self.assertEqual(result.zus.zdrowotna, Decimal("498.35"))
        self.assertEqual(result.zus.lacznie_do_zaplaty, Decimal("2425.11"))

        # PIT-28 (odliczenie wyłącznie ubezpieczeń społecznych, bez Funduszu Pracy)
        self.assertIsNotNone(result.pit28)
        self.assertEqual(result.pit28.przychod_laczny, Decimal("38969.00"))
        self.assertEqual(result.pit28.odliczenie_spoleczne, Decimal("1788.29"))
        self.assertEqual(result.pit28.odliczenie_zdrowotna_50, Decimal("249.18"))
        self.assertEqual(result.pit28.podstawa_opodatkowania, Decimal("36931.53"))
        self.assertEqual(result.pit28.zaliczka_pit28_zaokraglona, 4432)

        # VAT
        self.assertIsNotNone(result.vat)
        self.assertEqual(result.vat.vat_nalezy, Decimal("8962.87"))
        self.assertEqual(result.vat.vat_do_zaplaty_zaokraglony, 8567)

        # Paczka przelewów
        self.assertEqual(len(result.paczka_przelewow), 3)
        self.assertEqual(result.suma_wszystkich_zobowiazan, Decimal("15424.11"))

    def test_reports_generation(self):
        # Rozliczenie kwietnia z zapisem raportów
        SettlementService.settle_month(
            self.profile, "2026", "04", nadwyzka_vat_poprzedni=Decimal("217.10"), zapisz_raporty=True
        )

        target_dir = self.profile.katalog_firmy / "rozliczenia" / "2026" / "04"
        self.assertTrue((target_dir / "rozliczenie.md").exists())
        self.assertTrue((target_dir / "rozliczenie.json").exists())
        self.assertTrue((target_dir / "ewidencja-przychodow.md").exists())
        self.assertTrue((target_dir / "ewidencja-przychodow-sumy.md").exists())
        self.assertTrue((target_dir / "sprawozdanie.md").exists())

        ep_content = (target_dir / "ewidencja-przychodow.md").read_text(encoding="utf-8")
        self.assertIn("Ewidencja Przychodów – 2026-04", ep_content)
        self.assertIn("38969.00 zł", ep_content)
        self.assertIn("12%", ep_content)

        eps_content = (target_dir / "ewidencja-przychodow-sumy.md").read_text(encoding="utf-8")
        self.assertIn("Ewidencja Przychodów – Zestawienie Roczne i Sumy", eps_content)
        self.assertIn("Tabela 1:", eps_content)
        self.assertIn("Tabela 2:", eps_content)
        self.assertIn("SUMA (YTD)", eps_content)
        self.assertIn("SUMA ROCZNA", eps_content)

        spr_content = (target_dir / "sprawozdanie.md").read_text(encoding="utf-8")
        self.assertIn("Sprawozdanie z Czynności Księgowych i Audytu Podatkowego", spr_content)
        self.assertIn("Część I: Faktury Sprzedaży", spr_content)
        self.assertIn("Część II: Faktury Kosztowe", spr_content)
        self.assertIn("Część III: Podsumowanie Audytu", spr_content)
        self.assertIn("Klauzula informacyjna:", spr_content)

        rozl_content = (target_dir / "rozliczenie.md").read_text(encoding="utf-8")
        self.assertNotIn("Podatnik jest w 100% bezpieczny", rozl_content)
        self.assertIn("Klauzula informacyjna:", rozl_content)

    def test_tax_precautionary_principle_unaudited_expenses(self):
        """Weryfikuje zasadę ostrożności podatkowej (TAX-1): faktury bez audytu mają status DO_WYJASNIENIA i 0 zł VAT."""
        result = SettlementService.settle_month(
            self.profile, "2026", "04", nadwyzka_vat_poprzedni=Decimal("217.10"), zapisz_raporty=False
        )
        # Symulacja braku audytu dla dokumentów kosztowych
        result.ledger.audyt_kosztow.clear()
        sprawozdanie = result.generate_sprawozdanie_report()

        self.assertNotIn("✅ 100% Firmowy", sprawozdanie)
        self.assertIn("⚠️ Do wyjaśnienia", sprawozdanie)
        self.assertIn("Brak audytu pozycji – wymaga decyzji podatnika przed odliczeniem", sprawozdanie)
        self.assertIn("**0.00 zł**", sprawozdanie)

    def test_settle_october_2026_professional_accountant_mode(self):
        """Test rozliczenia 2026-10 w trybie księgowego profesjonalnego (zasada kasowa + wyłączenie FP)."""
        import pathlib

        p_path = pathlib.Path("firmy/7770001122-CloudTech_Solutions_Jan_Kowalski")
        if not (p_path / "faktury" / "2026" / "10" / "sprzedaz").exists():
            self.skipTest("Brak danych testowych za 2026-10 dla firmy testowej")
        real_profile = CompanyProfile.load_from_dir(p_path)
        result = SettlementService.settle_month(real_profile, "2026", "10", zapisz_raporty=False)

        self.assertEqual(result.pit28.zaliczka_pit28_zaokraglona, 6276)
        self.assertEqual(result.vat.vat_do_zaplaty_zaokraglony, 7327)
        self.assertEqual(result.zus.lacznie_do_zaplaty, Decimal("2757.34"))

    def test_settle_may_2026_retroactive_correction(self):
        """Test rozliczenia 2026-05: korekta wsteczna 1/KOR/06/2026 (-4000 zł) koryguje przychód maja dla PIT-28."""
        import pathlib

        p_path = pathlib.Path("firmy/7770001122-CloudTech_Solutions_Jan_Kowalski")
        if not (p_path / "faktury" / "2026" / "05" / "sprzedaz").exists():
            self.skipTest("Brak danych testowych za 2026-05 dla firmy testowej")
        real_profile = CompanyProfile.load_from_dir(p_path)
        result = SettlementService.settle_month(real_profile, "2026", "05", zapisz_raporty=False)

        # Przychód z maja: 1499 + 42200 - 4000 = 39699 zł
        self.assertEqual(result.pit28.przychod_laczny, Decimal("39699.00"))
        # Zaliczka PIT-28 identyczna jak u księgowego: 4516 zł
        self.assertEqual(result.pit28.zaliczka_pit28_zaokraglona, 4516)
        # VAT należny za maj bez korekty czerwcowej: 10050.77 zł
        self.assertEqual(result.vat.vat_nalezy, Decimal("10050.77"))


if __name__ == "__main__":
    unittest.main()
