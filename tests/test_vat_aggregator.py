import unittest
from decimal import Decimal

from src.skills.vat_aggregator import VATAggregationReport, VATAggregator


class TestVATAggregator(unittest.TestCase):
    def test_aggregation_cloudtech_2026(self):
        from pathlib import Path

        p_path = Path("firmy/7770001122-CloudTech_Solutions_Jan_Kowalski")
        if (p_path / "rozliczenia" / "2026").exists():
            base_dir = "firmy"
        elif Path("examples/firmy/7770001122-CloudTech_Solutions_Jan_Kowalski/rozliczenia/2026").exists():
            base_dir = "examples/firmy"
        else:
            self.skipTest("Brak rocznych rozliczeń testowych 2026 dla firmy testowej")
        report = VATAggregator.aggregate(base_dir, "7770001122", "2026")
        self.assertIsInstance(report, VATAggregationReport)
        self.assertEqual(report.nip, "7770001122")
        self.assertEqual(report.rok, "2026")
        self.assertGreaterEqual(len(report.zamkniete_miesiace), 5)
        self.assertGreater(report.laczny_vat_odliczony, Decimal("3000.00"))

        # Sprawdzenie kategorii podatkowych
        kat_p = report.kategorie_podatkowe
        self.assertIn("FIRMOWY_100", kat_p)
        self.assertIn("SAMOCHOD_50", kat_p)
        self.assertGreater(kat_p["FIRMOWY_100"].suma_vat_odliczony, Decimal("2500.00"))
        self.assertGreater(kat_p["SAMOCHOD_50"].suma_vat_odliczony, Decimal("150.00"))

        # Sprawdzenie sumy odliczeń wg kategorii biznesowych
        suma_biz = sum(b.suma_vat_odliczony for b in report.kategorie_biznesowe.values())
        self.assertEqual(suma_biz, report.laczny_vat_odliczony)

        # Sprawdzenie eksportu
        md = report.to_markdown()
        self.assertIn("Raport Agregacji Odliczeń VAT – 2026", md)
        d = report.to_dict()
        self.assertEqual(d["laczny_vat_odliczony"], str(report.laczny_vat_odliczony))


if __name__ == "__main__":
    unittest.main()
