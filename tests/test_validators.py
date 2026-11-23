"""
tests/test_validators.py
Testy algorytmicznej walidacji polskich identyfikatorów fiskalnych i bankowych (VAL-1).
"""

import unittest

from src.core.validators import (
    calculate_nrb_checksum,
    clean_nip,
    clean_nrb,
    clean_regon,
    format_nrb,
    generate_us_microaccount,
    generate_zus_nrs_account,
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

    def test_format_nrb(self):
        # 26 cyfr z prefiksem PL
        raw = "80101000712222777000112200"
        formatted = format_nrb(raw, include_prefix=True)
        self.assertEqual(formatted, "PL 80 1010 0071 2222 7770 0011 2200")

        # Bez prefiksu PL
        formatted_no_prefix = format_nrb(raw, include_prefix=False)
        self.assertEqual(formatted_no_prefix, "80 1010 0071 2222 7770 0011 2200")

        # Z istniejącym PL i myślnikami/spacjami
        messy = "PL 80-1010 0071-2222 7770 0011 2200"
        self.assertEqual(format_nrb(messy), "PL 80 1010 0071 2222 7770 0011 2200")

        # Krótki/błędny ciąg zwraca oryginał
        self.assertEqual(format_nrb("12345"), "12345")
        self.assertEqual(format_nrb(""), "")
        self.assertEqual(format_nrb(None), "")

    def test_calculate_nrb_checksum(self):
        # BBAN 24 cyfry dla NBP Bydgoszcz i NIP 7770001122
        bban = "101000712222777000112200"
        checksum = calculate_nrb_checksum(bban)
        self.assertEqual(checksum, "80")

        # Błędna długość BBAN
        with self.assertRaises(ValueError):
            calculate_nrb_checksum("123")

    def test_generate_us_microaccount(self):
        # Dla NIP 7770001122
        account = generate_us_microaccount("7770001122")
        self.assertEqual(len(account), 26)
        self.assertEqual(account, "80101000712222777000112200")
        is_valid, err = validate_nrb(account)
        self.assertTrue(is_valid, f"Wygenerowany mikrorachunek US jest niepoprawny: {err}")

        # Z myślnikami i PL
        self.assertEqual(generate_us_microaccount("PL 777-000-11-22"), "80101000712222777000112200")

    def test_generate_zus_nrs_account(self):
        # Dla NIP 7770001122
        account = generate_zus_nrs_account("7770001122")
        self.assertEqual(len(account), 26)
        self.assertEqual(account, "50101010230000267770001122")
        is_valid, err = validate_nrb(account)
        self.assertTrue(is_valid, f"Wygenerowany rachunek ZUS NRS jest niepoprawny: {err}")

    def test_company_profile_accounts(self):
        from src.core.company import CompanyProfile

        profile = CompanyProfile(nip="7770001122", nazwa="Test Firma")
        self.assertEqual(profile.mikrorachunek_us, "80101000712222777000112200")
        self.assertEqual(profile.rachunek_zus, "50101010230000267770001122")
        self.assertEqual(format_nrb(profile.mikrorachunek_us), "PL 80 1010 0071 2222 7770 0011 2200")
        self.assertEqual(format_nrb(profile.rachunek_zus), "PL 50 1010 1023 0000 2677 7000 1122")


if __name__ == "__main__":
    unittest.main()
