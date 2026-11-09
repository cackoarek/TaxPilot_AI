"""
Testy jednostkowe silnika rozliczeń podatkowych (SettlementService, BookkeepingService, ZUS, PIT-28, VAT).
"""

import unittest
from decimal import Decimal

from src.core.company import CompanyProfile
from src.level_3_tax_settlement.settlement_service import SettlementService
from tests.fixtures import setup_test_company, cleanup_test_company


class TestSettlementService(unittest.TestCase):

    def setUp(self):
        self.profile = setup_test_company()
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
        self.assertEqual(result.zus.podstawa_spoleczne, Decimal("5304.00"))
        self.assertEqual(result.zus.suma_spoleczne, Decimal("1808.14"))
        self.assertEqual(result.zus.zdrowotna, Decimal("486.44"))
        self.assertEqual(result.zus.lacznie_do_zaplaty, Decimal("2294.58"))

        # PIT-28
        self.assertIsNotNone(result.pit28)
        self.assertEqual(result.pit28.przychod_laczny, Decimal("38969.00"))
        self.assertEqual(result.pit28.odliczenie_spoleczne, Decimal("1808.14"))
        self.assertEqual(result.pit28.odliczenie_zdrowotna_50, Decimal("243.22"))
        self.assertEqual(result.pit28.podstawa_opodatkowania, Decimal("36917.64"))
        self.assertEqual(result.pit28.zaliczka_pit28_zaokraglona, 4430)

        # VAT
        self.assertIsNotNone(result.vat)
        self.assertEqual(result.vat.vat_nalezy, Decimal("8962.87"))
        self.assertEqual(result.vat.vat_do_zaplaty_zaokraglony, 8567)

        # Paczka przelewów
        self.assertEqual(len(result.paczka_przelewow), 3)
        self.assertEqual(result.suma_wszystkich_zobowiazan, Decimal("15291.58"))

    def test_reports_generation(self):
        # Rozliczenie kwietnia z zapisem raportów
        result = SettlementService.settle_month(
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


if __name__ == "__main__":
    unittest.main()
