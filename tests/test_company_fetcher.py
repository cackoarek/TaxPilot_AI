"""
Testy jednostkowe modułu CompanyFetcher oraz inicjalizacji firmy (init-firma).
Testy są w 100% hermetyczne (mockowane zapytania HTTP).
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import shutil
import tempfile
import json

from src.core.company import CompanyProfile, FormaOpodatkowania, TypZUS
from src.level_1_ingestion.company_fetcher import CompanyFetcher


class TestCompanyFetcher(unittest.TestCase):

    def test_clean_nip(self):
        self.assertEqual(CompanyFetcher.clean_nip("777-000-11-22"), "7770001122")
        self.assertEqual(CompanyFetcher.clean_nip(" PL 777 000 11 22 "), "7770001122")
        self.assertEqual(CompanyFetcher.clean_nip("1234567890"), "1234567890")

    @patch("requests.get")
    def test_fetch_mf_biala_lista_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "subject": {
                    "name": "TEST IT SPÓŁKA CYWILNA",
                    "nip": "7770001122",
                    "statusVat": "Czynny",
                    "regon": "123456789",
                    "workingAddress": "ul. Testowa 1, 00-001 Warszawa",
                    "accountNumbers": ["12345678901234567890123456"]
                }
            }
        }
        mock_get.return_value = mock_response

        res = CompanyFetcher.fetch_from_mf_biala_lista("777-000-11-22")
        self.assertIsNotNone(res)
        self.assertEqual(res["nazwa"], "TEST IT SPÓŁKA CYWILNA")
        self.assertEqual(res["nip"], "7770001122")
        self.assertEqual(res["regon"], "123456789")
        self.assertEqual(res["adres"], "ul. Testowa 1, 00-001 Warszawa")
        self.assertTrue(res["platnik_vat"])
        self.assertEqual(res["zrodlo"], "MF_BIALA_LISTA")

    @patch("requests.get")
    def test_fetch_mf_biala_lista_not_found_404(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        res = CompanyFetcher.fetch_from_mf_biala_lista("7770001122")
        self.assertIsNotNone(res)
        self.assertFalse(res["platnik_vat"])
        self.assertFalse(res["blad_polaczenia"])
        self.assertIn("Niezarejestrowany", res["status_vat"])

    @patch("requests.get")
    def test_fetch_mf_biala_lista_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Brak sieci")

        res = CompanyFetcher.fetch_from_mf_biala_lista("7770001122")
        self.assertIsNotNone(res)
        self.assertTrue(res["blad_polaczenia"])
        self.assertIn("Brak połączenia", res["status_vat"])

    @patch("requests.get")
    def test_fetch_ceidg_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "firmy": [
                {
                    "nazwa": "PROGRAMOWANIE JAN KOWALSKI",
                    "pkd": ["62.01.Z", "62.02.Z", "58.29.Z"],
                    "pkdGlowny": "62.01.Z",
                    "status": "AKTYWNY"
                }
            ]
        }
        mock_get.return_value = mock_response

        res = CompanyFetcher.fetch_from_ceidg("7770001122", api_token="dummy_token")
        self.assertIsNotNone(res)
        self.assertEqual(res["pkd_glowny"], "62.01.Z")
        self.assertIn("62.01.Z", res["kody_pkd"])
        self.assertIn("62.02.Z", res["kody_pkd"])

    def test_company_profile_with_pkd(self):
        profile = CompanyProfile(
            nip="7770001122",
            nazwa="Test PKD Company",
            kody_pkd=["62.01.Z", "62.02.Z"],
            regon="123456789",
            adres="ul. Prosta 1, Warszawa"
        )
        d = profile.to_dict()
        self.assertEqual(d["kody_pkd"], ["62.01.Z", "62.02.Z"])
        self.assertEqual(d["regon"], "123456789")
        self.assertEqual(d["adres"], "ul. Prosta 1, Warszawa")

        reloaded = CompanyProfile.from_dict(d)
        self.assertEqual(reloaded.kody_pkd, ["62.01.Z", "62.02.Z"])
        self.assertEqual(reloaded.regon, "123456789")
        self.assertEqual(reloaded.adres, "ul. Prosta 1, Warszawa")


if __name__ == "__main__":
    unittest.main()

