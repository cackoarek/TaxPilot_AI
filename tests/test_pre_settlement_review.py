"""
Testy jednostkowe modułu weryfikacji i przeglądu dokumentów przed rozliczeniem (PreSettlementReview).
"""

import unittest
from decimal import Decimal

from src.core.company import CompanyProfile
from src.skills.pre_settlement_review import PreSettlementReview
from tests.fixtures import setup_test_company, cleanup_test_company


class TestPreSettlementReview(unittest.TestCase):

    def setUp(self):
        self.profile = setup_test_company()
        self.assertIsNotNone(self.profile)

    def tearDown(self):
        cleanup_test_company(self.profile)

    def test_build_review_april_2026(self):
        review = PreSettlementReview.build(self.profile, "2026", "04")

        # Sprawdzenie przychodów (sprzedaż)
        self.assertEqual(len(review.sprzedaz), 2)
        self.assertEqual(review.laczna_sprzedaz_netto, Decimal("38969.00"))
        self.assertEqual(review.laczna_sprzedaz_vat, Decimal("8962.87"))
        self.assertEqual(review.laczna_sprzedaz_brutto, Decimal("47931.87"))

        # Sprawdzenie kosztów (zakupy)
        self.assertEqual(len(review.koszty), 8)
        self.assertTrue(review.laczny_koszt_netto > Decimal("0.00"))

        # Sprawdzenie generowania Markdown
        md = review.generate_markdown()
        self.assertIn("Faktury Sprzedaży (Przychody)", md)
        self.assertIn("Faktury Kosztowe (Zakupy)", md)
        self.assertIn("38969.00 zł", md)


if __name__ == "__main__":
    unittest.main()
