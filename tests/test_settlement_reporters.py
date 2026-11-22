"""
Testy jednostkowe wyodrębnionych generatorów raportów podatkowych:
- SettlementMarkdownReporter
- LedgerMarkdownReporter
- AuditMarkdownReporter
- format_rate_pct
"""

import unittest
from decimal import Decimal

from src.level_3_tax_settlement.reports import (
    AuditMarkdownReporter,
    LedgerMarkdownReporter,
    SettlementMarkdownReporter,
    format_rate_pct,
)
from src.level_3_tax_settlement.settlement_service import SettlementService
from tests.fixtures import cleanup_test_company, setup_isolated_test_company


class TestSettlementReporters(unittest.TestCase):
    def setUp(self):
        self.profile = setup_isolated_test_company()
        self.result = SettlementService.settle_month(
            self.profile, "2026", "04", nadwyzka_vat_poprzedni=Decimal("217.10"), zapisz_raporty=False
        )

    def tearDown(self):
        cleanup_test_company(self.profile)

    def test_format_rate_pct(self):
        self.assertEqual(format_rate_pct(Decimal("0.12")), "12%")
        self.assertEqual(format_rate_pct(Decimal("0.085")), "8,5%")
        self.assertEqual(format_rate_pct(Decimal("0.03")), "3%")
        self.assertEqual(format_rate_pct(Decimal("0.15")), "15%")
        self.assertEqual(format_rate_pct(Decimal("0.055")), "5,5%")

    def test_settlement_markdown_reporter(self):
        md = SettlementMarkdownReporter.generate(self.result)
        self.assertIsInstance(md, str)
        self.assertIn("# Raport Rozliczenia Miesięcznego – 2026-04", md)
        self.assertIn("CloudTech Solutions Jan Kowalski", md)
        self.assertIn("7770001122", md)
        self.assertIn("1. Paczka Przelewów Podatkowych", md)
        self.assertIn("ZUS (Społeczne + Zdrowotna)", md)
        self.assertIn("Urząd Skarbowy – Ryczałt PIT-28", md)
        self.assertIn("Urząd Skarbowy – Podatek VAT-7", md)
        self.assertIn("Łączna suma obciążeń za ten miesiąc", md)
        self.assertIn("Klauzula informacyjna:", md)

    def test_ledger_markdown_reporter_monthly(self):
        md = LedgerMarkdownReporter.generate_monthly(self.result)
        self.assertIsInstance(md, str)
        self.assertIn("# Ewidencja Przychodów – 2026-04", md)
        self.assertIn("12%", md)
        self.assertIn("38969.00 zł", md)
        self.assertIn("Podsumowanie Ewidencji Przychodów za 2026-04", md)

    def test_ledger_markdown_reporter_ytd(self):
        md = LedgerMarkdownReporter.generate_ytd(self.result)
        self.assertIsInstance(md, str)
        self.assertIn("Ewidencja Przychodów – Zestawienie Roczne i Sumy", md)
        self.assertIn("Tabela 1: Przychody w Poszczególnych Miesiącach oraz Składki Ubezpieczeń do Odliczenia", md)
        self.assertIn("Tabela 2: Miesiące w Roku z Podziałem na Podstawę i Ryczałt wg Wysokości Podatku", md)
        self.assertIn("SUMA (YTD)", md)
        self.assertIn("SUMA ROCZNA", md)

    def test_audit_markdown_reporter(self):
        md = AuditMarkdownReporter.generate(self.result)
        self.assertIsInstance(md, str)
        self.assertIn("Sprawozdanie z Czynności Księgowych i Audytu Podatkowego", md)
        self.assertIn("Część I: Faktury Sprzedaży", md)
        self.assertIn("Część II: Faktury Kosztowe", md)
        self.assertIn("Część III: Podsumowanie Audytu", md)
        self.assertIn("Klauzula informacyjna:", md)
