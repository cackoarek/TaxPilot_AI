import unittest
from decimal import Decimal
from src.skills.vat_aggregator import VATAggregator, VATAggregationReport


class TestVATAggregator(unittest.TestCase):
    def test_aggregation_smart_it_2026(self):
        from pathlib import Path
        if not Path("firmy/5322030067-Smart_IT_Solutions_Arkadiusz_Cacko").exists():
            self.skipTest("Firma 5322030067 nie istnieje w środowisku testowym")
        report = VATAggregator.aggregate("firmy", "5322030067", "2026")
        self.assertIsInstance(report, VATAggregationReport)
        self.assertEqual(report.nip, "5322030067")
        self.assertEqual(report.rok, "2026")
        self.assertIn(len(report.zamkniete_miesiace), (9, 10))
        self.assertGreater(report.laczny_vat_odliczony, Decimal("4000.00"))
        
        # Sprawdzenie kategorii podatkowych
        kat_p = report.kategorie_podatkowe
        self.assertIn("FIRMOWY_100", kat_p)
        self.assertIn("SAMOCHOD_50", kat_p)
        self.assertGreater(kat_p["FIRMOWY_100"].suma_vat_odliczony, Decimal("2500.00"))
        self.assertGreater(kat_p["SAMOCHOD_50"].suma_vat_odliczony, Decimal("1000.00"))
        
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
