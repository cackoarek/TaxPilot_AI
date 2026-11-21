import unittest
from decimal import Decimal
from src.skills.vat_aggregator import VATAggregator, VATAggregationReport


class TestVATAggregator(unittest.TestCase):
    def test_aggregation_smart_it_2026(self):
        report = VATAggregator.aggregate("firmy", "5322030067", "2026")
        self.assertIsInstance(report, VATAggregationReport)
        self.assertEqual(report.nip, "5322030067")
        self.assertEqual(report.rok, "2026")
        self.assertEqual(len(report.zamkniete_miesiace), 10)
        self.assertEqual(report.laczny_vat_odliczony, Decimal("4862.76"))
        
        # Sprawdzenie kategorii podatkowych
        kat_p = report.kategorie_podatkowe
        self.assertIn("FIRMOWY_100", kat_p)
        self.assertIn("SAMOCHOD_50", kat_p)
        self.assertEqual(kat_p["FIRMOWY_100"].suma_vat_odliczony, Decimal("3248.65"))
        self.assertEqual(kat_p["SAMOCHOD_50"].suma_vat_odliczony, Decimal("1614.11"))
        
        # Sprawdzenie sumy odliczeń wg kategorii biznesowych
        suma_biz = sum(b.suma_vat_odliczony for b in report.kategorie_biznesowe.values())
        self.assertEqual(suma_biz, Decimal("4862.76"))

        # Sprawdzenie eksportu
        md = report.to_markdown()
        self.assertIn("Raport Agregacji Odliczeń VAT – 2026", md)
        d = report.to_dict()
        self.assertEqual(d["laczny_vat_odliczony"], "4862.76")


if __name__ == "__main__":
    unittest.main()
