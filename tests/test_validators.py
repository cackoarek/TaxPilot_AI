"""
tests/test_validators.py
Testy algorytmicznej walidacji polskich identyfikatorów fiskalnych i bankowych (VAL-1).
"""

import unittest

from src.core.validators import (
    clean_nip,
    clean_nrb,
    clean_regon,
    validate_nip,
    validate_nrb,
    validate_regon,
)


class TestValidators(unittest.TestCase):
    def test_clean_nip(self):
        self.assertEqual(clean_nip("PL 526-025-02-74"), "5260250274")
        self.assertEqual(clean_nip("  526 025 02 74  "), "5260250274")
        self.assertEqual(clean_nip("pl7770001122"), "7770001122")
        self.assertEqual(clean_nip(""), "")
        self.assertEqual(clean_nip(None), "")

    def test_validate_nip_valid(self):
        # 5260250274 - Ministerstwo Finansów
        is_valid, err = validate_nip("526-025-02-74")
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

        # 5322030067 - Prawidłowy NIP
        is_valid, err = validate_nip("5322030067")
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

    def test_validate_nip_test_fixtures(self):
        # NIP-y testowe projektu powinny być akceptowane domyślnie
        is_valid, err = validate_nip("7770001122", allow_test_nips=True)
        self.assertTrue(is_valid)

        is_valid, err = validate_nip("1111111111", allow_test_nips=True)
        self.assertTrue(is_valid)

        # Ale odrzucane przy wyłączonej fladze allow_test_nips
        is_valid, err = validate_nip("7770001122", allow_test_nips=False)
        self.assertFalse(is_valid)
        self.assertIn("Błędna cyfra kontrolna NIP", err)

    def test_validate_nip_invalid(self):
        # Zbyt krótki / pusty
        self.assertFalse(validate_nip("")[0])
        self.assertFalse(validate_nip("12345")[0])
        self.assertFalse(validate_nip("12345678901")[0])

        # Błędna cyfra kontrolna
        is_valid, err = validate_nip("5260250275")
        self.assertFalse(is_valid)
        self.assertIn("Błędna cyfra kontrolna NIP", err)

    def test_clean_regon(self):
        self.assertEqual(clean_regon(" 123 456 785 "), "123456785")
        self.assertEqual(clean_regon(""), "")
        self.assertEqual(clean_regon(None), "")

    def test_validate_regon_9(self):
        # 123456785: 1*8 + 2*9 + 3*2 + 4*3 + 5*4 + 6*5 + 7*6 + 8*7 = 8+18+6+12+20+30+42+56 = 192 % 11 = 5
        is_valid, err = validate_regon("123456785")
        self.assertTrue(is_valid)

        # Błędny REGON-9
        is_valid, err = validate_regon("123456789")
        self.assertFalse(is_valid)
        self.assertIn("Błędna cyfra kontrolna REGON-9", err)

        # Nieprawidłowa długość
        self.assertFalse(validate_regon("12345678")[0])

    def test_validate_regon_14(self):
        # 12345678512347 (przykładowy 14-cyfrowy)
        # Błędny REGON-14
        is_valid, err = validate_regon("12345678512340")
        self.assertFalse(is_valid)

    def test_clean_nrb(self):
        self.assertEqual(clean_nrb("PL 10 1050 1445 1000 0022 7100 1234"), "10105014451000002271001234")
        self.assertEqual(clean_nrb(""), "")
        self.assertEqual(clean_nrb(None), "")

    def test_validate_nrb(self):
        # Prawidłowy rachunek bankowy (zgodny z ISO 7064 MOD 97-10)
        # NBP rachunek centralny: 92 1010 0000 0000 1322 3100 0000
        valid_nrb = "92101000000000132231000000"
        is_valid, err = validate_nrb(valid_nrb)
        self.assertTrue(is_valid, f"Błąd walidacji: {err}")

        # Zły numer rachunku (zmieniona cyfra kontrolna)
        invalid_nrb = "99101000000000132231000000"
        is_valid, err = validate_nrb(invalid_nrb)
        self.assertFalse(is_valid)
        self.assertIn("Nieprawidłowa suma kontrolna", err)

        # Zła długość
        self.assertFalse(validate_nrb("12345")[0])


if __name__ == "__main__":
    unittest.main()
