"""
tests/test_web_qr.py
Testy jednostkowe i integracyjne generatora kodów QR przelewów bankowych (Standard ZBP) - Kamień Milowy M4.
"""

import unittest
from decimal import Decimal

from fastapi.testclient import TestClient

from src.web.app import app
from src.web.services.qr_generator import (
    clean_account_number,
    format_zbp_payload,
    generate_qr_base64_data_uri,
    get_transfer_qr_package,
)


class TestWebQR(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from src.web.config import COOKIE_ACTIVE_NIP

        self.client.cookies[COOKIE_ACTIVE_NIP] = "7770001122"

    def test_clean_account_number(self):
        """Test oczyszczania numeru konta ze spacji i myślników."""
        raw = "PL 10 1010-0055 0225 7770 0011 2200"
        clean = clean_account_number(raw)
        self.assertEqual(clean, "10101000550225777000112200")

    def test_format_zbp_payload(self):
        """Test formatowania ciągu danych według standardu Związku Banków Polskich."""
        rachunek = "10101000550225777000112200"
        kwota = Decimal("1250.50")
        nazwa = "Urząd Skarbowy Warszawa"
        tytul = "PIT-28 za 2026-01"

        payload = format_zbp_payload(rachunek, kwota, nazwa, tytul)

        # Oczekiwany format ZBP: ||rachunek|kwota_w_groszach|nazwa|tytul|||
        self.assertTrue(payload.startswith("||10101000550225777000112200|125050|"))
        self.assertIn("Urząd Skarbowy Warszawa", payload)
        self.assertIn("PIT-28 za 2026-01", payload)
        self.assertTrue(payload.endswith("|||"))

    def test_generate_qr_base64_data_uri(self):
        """Test generowania obrazu QR jako Data URI base64."""
        payload = "||10101000550225777000112200|0125050|US|PIT-28|||"
        uri = generate_qr_base64_data_uri(payload)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertTrue(len(uri) > 300)

    def test_get_transfer_qr_package(self):
        """Test przygotowania kompletnej paczki przelewu."""
        pkg = get_transfer_qr_package(
            typ="PIT-28",
            rachunek="PL10101000550225777000112200",
            kwota="450.00",
            rok="2026",
            miesiac="01",
            nip="7770001122",
        )
        self.assertEqual(pkg["typ"], "PIT-28")
        self.assertIn("Mikrorachunek", pkg["odbiorca"])
        self.assertEqual(pkg["kwota"], "450.00")
        self.assertEqual(pkg["rachunek_sformatowany"], "PL 10 1010 0055 0225 7770 0011 2200")
        self.assertTrue(pkg["qr_data_uri"].startswith("data:image/png;base64,"))
        self.assertIn("PIT-28 za 2026-01 NIP 7770001122", pkg["tytul"])

    def test_qr_modal_endpoints_pit28(self):
        """Test endpointu GET /api/settlement/qr/pit28."""
        response = self.client.get("/api/settlement/qr/pit28")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Przelew PIT-28", html)
        self.assertIn("Standard ZBP / Elixir", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("Numer Rachunku (IBAN):", html)
        self.assertIn("Kwota do zapłaty:", html)
        self.assertIn("PL 80 1010 0071 2222 7770 0011 2200", html)

    def test_qr_modal_endpoints_vat7(self):
        """Test endpointu GET /api/settlement/qr/vat7."""
        response = self.client.get("/api/settlement/qr/vat7")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Przelew VAT-7", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("PL 80 1010 0071 2222 7770 0011 2200", html)

    def test_qr_modal_endpoints_zus(self):
        """Test endpointu GET /api/settlement/qr/zus."""
        response = self.client.get("/api/settlement/qr/zus")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Przelew ZUS", html)
        self.assertIn("Indywidualny Rachunek Składkowy NRS", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("PL 50 1010 1023 0000 2677 7000 1122", html)

    def test_qr_modal_invalid_type_returns_400(self):
        """Test niepoprawnego typu przelewu."""
        response = self.client.get("/api/settlement/qr/nieznany-typ")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
