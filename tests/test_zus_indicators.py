"""
Testy jednostkowe modułu wskaźników makroekonomicznych ZUS/GUS.
"""

import unittest
from decimal import Decimal

from src.core.company import FormaOpodatkowania, TypZUS
from src.skills.zus_indicators import get_zus_indicators
from src.skills.zus_tools import calculate_zus


class TestZUSIndicators(unittest.TestCase):
    def test_official_2026_indicators(self):
        macro = get_zus_indicators("2026")
        self.assertEqual(macro.rok, "2026")
        self.assertEqual(macro.podstawa_pelny_zus, Decimal("5652.00"))
        self.assertEqual(macro.podstawa_preferencyjny_zus, Decimal("1441.80"))
        self.assertEqual(macro.przecietne_wynagrodzenie_zdrowotna, Decimal("9228.64"))
        self.assertEqual(macro.zrodlo, "OFICJALNE_GUS")
        self.assertIsNone(macro.ostrzezenie)

    def test_official_2025_indicators(self):
        macro = get_zus_indicators("2025")
        self.assertEqual(macro.rok, "2025")
        self.assertEqual(macro.podstawa_pelny_zus, Decimal("5203.80"))
        self.assertEqual(macro.podstawa_preferencyjny_zus, Decimal("1399.80"))
        self.assertEqual(macro.przecietne_wynagrodzenie_zdrowotna, Decimal("8549.18"))
        self.assertEqual(macro.zrodlo, "OFICJALNE_GUS")

    def test_fallback_future_year(self):
        macro = get_zus_indicators("2028")
        self.assertEqual(macro.rok, "2028")
        self.assertEqual(macro.zrodlo, "PROGNOZA_SZACOWANA")
        self.assertIsNotNone(macro.ostrzezenie)
        self.assertIn("Zastosowano prognozowane wskaźniki ZUS", macro.ostrzezenie)
        self.assertTrue(macro.przecietne_wynagrodzenie_zdrowotna > Decimal("9228.64"))

    def test_profile_override(self):
        overrides = {
            "custom_podstawa_spoleczne": Decimal("5800.00"),
            "custom_przecietne_wynagrodzenie": Decimal("9500.00"),
        }
        macro = get_zus_indicators("2026", profile_overrides=overrides)
        self.assertEqual(macro.podstawa_pelny_zus, Decimal("5800.00"))
        self.assertEqual(macro.przecietne_wynagrodzenie_zdrowotna, Decimal("9500.00"))
        self.assertEqual(macro.zrodlo, "PROFIL_UZYTKOWNIKA")

    def test_calculate_zus_with_official_2026(self):
        # II próg ryczałtu (60k-300k): 100% * 9228.64 * 0.09 = 830.58 zł
        res = calculate_zus(
            rok="2026",
            miesiac="08",
            typ_zus=TypZUS.PELNY_ZUS,
            chorobowe_dobrowolne=True,
            forma_opodatkowania=FormaOpodatkowania.RYCZALT,
            przychod_roczny_narastajaco=Decimal("150000.00"),
        )
        self.assertEqual(res.suma_spoleczne, Decimal("1926.76"))
        self.assertEqual(res.zdrowotna, Decimal("830.58"))
        self.assertEqual(res.odliczenie_zdrowotna_ryczalt_50, Decimal("415.29"))
        self.assertEqual(res.lacznie_do_zaplaty, Decimal("2757.34"))
        self.assertEqual(res.zrodlo_wskaznikow, "OFICJALNE_GUS")

    def test_cache_save_and_load(self):
        import tempfile
        from pathlib import Path

        from src.skills.zus_indicators import ZUSMacroParams, load_from_cache, save_to_cache

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "test_zus_cache.json"
            sample = ZUSMacroParams(
                rok="2028",
                podstawa_pelny_zus=Decimal("6000.00"),
                podstawa_preferencyjny_zus=Decimal("1800.00"),
                przecietne_wynagrodzenie_zdrowotna=Decimal("10000.00"),
                zrodlo="POBRANE_ONLINE",
                ostrzezenie=None,
            )
            save_to_cache(sample, cache_path=cache_file)
            loaded = load_from_cache("2028", cache_path=cache_file)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.rok, "2028")
            self.assertEqual(loaded.podstawa_pelny_zus, Decimal("6000.00"))
            self.assertEqual(loaded.przecietne_wynagrodzenie_zdrowotna, Decimal("10000.00"))
            self.assertEqual(loaded.zrodlo, "POBRANE_ONLINE")

            # Test integracji w get_zus_indicators
            macro = get_zus_indicators("2028", cache_path=cache_file)
            self.assertEqual(macro.podstawa_pelny_zus, Decimal("6000.00"))


if __name__ == "__main__":
    unittest.main()
