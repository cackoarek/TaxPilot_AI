"""
Moduł integracji z publicznymi rejestrami przedsiębiorców w Polsce.
Pozwala na automatyczne pobieranie danych firmy (nazwa, adres, REGON, status VAT, kody PKD):
1. Biała Lista Podatników VAT (Ministerstwo Finansów) - publiczne API bez konieczności posiadania kluczy.
2. Hurtownia Danych CEIDG (dane.biznes.gov.pl) - oficjalne API CEIDG z kodami PKD.
"""

from typing import Dict, Any, Optional, List
import re
import os
import requests
from datetime import datetime


class CompanyFetcher:
    """
    Pobiera dane rejestrowe firmy na podstawie numeru NIP z rejestrów publicznych.
    """

    MF_API_URL = "https://wl-api.mf.gov.pl/api/search/nip"
    MF_CHECK_URL = "https://wl-api.mf.gov.pl/api/check/nip"
    CEIDG_API_URL = "https://dane.biznes.gov.pl/api/ceidg/v2/firmy"

    @staticmethod
    def clean_nip(nip: str) -> str:
        return re.sub(r"[^0-9]", "", nip)

    @classmethod
    def check_bank_account_mf(
        cls, nip: str, account: str, date_str: Optional[str] = None, timeout: int = 5
    ) -> Dict[str, Any]:
        """
        Weryfikuje powiązanie pary NIP + numer rachunku w dedykowanym endpoincie API MF:
        GET /api/check/nip/{nip}/bank-account/{bankAccount}?date={date}
        
        Kluczowe dla rachunków wirtualnych (subkont masowych płatności, np. Play, Orange, PGE),
        które NIE są publikowane w wykazie ogólnym /api/search/nip, lecz są potwierdzane
        przez algorytmy bankowe zintegrowane z API MF.
        """
        clean_nip = cls.clean_nip(nip)
        clean_acc = re.sub(r"[^0-9]", "", account or "")
        if not clean_nip or len(clean_nip) != 10 or not clean_acc or len(clean_acc) != 26:
            return {"assigned": False, "blad_polaczenia": False}

        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        url = f"{cls.MF_CHECK_URL}/{clean_nip}/bank-account/{clean_acc}?date={date_str}"
        headers = {"User-Agent": "TaxPilot_AI/1.0"}

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                assigned = data.get("result", {}).get("accountAssigned") == "TAK"
                return {
                    "assigned": assigned,
                    "request_id": data.get("result", {}).get("requestId"),
                    "blad_polaczenia": False,
                }
            return {"assigned": False, "blad_polaczenia": False}
        except requests.RequestException:
            return {"assigned": False, "blad_polaczenia": True}
        except Exception:
            return {"assigned": False, "blad_polaczenia": True}

    @classmethod
    def fetch_from_mf_biala_lista(cls, nip: str, date_str: Optional[str] = None, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Odpytuje Białą Listę Podatników VAT (Ministerstwo Finansów).
        Nie wymaga rejestracji ani klucza API.
        Zwraca: nazwa, REGON, adres, status VAT, numery kont bankowych zgłoszone w US.
        """
        clean_nip = cls.clean_nip(nip)
        if not clean_nip or len(clean_nip) != 10:
            return None

        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        url = f"{cls.MF_API_URL}/{clean_nip}?date={date_str}"
        headers = {"User-Agent": "TaxPilot_AI/1.0"}

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                # 404 oznacza brak podmiotu w wykazie (ale sieć działa poprawnie)
                if resp.status_code == 404:
                    return {
                        "nip": clean_nip,
                        "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                        "platnik_vat": False,
                        "blad_polaczenia": False,
                        "zrodlo": "MF_BIALA_LISTA"
                    }
                # Błędy serwera lub limitu zapytań (np. 429, 500, 503)
                return {
                    "nip": clean_nip,
                    "status_vat": f"Błąd serwisu MF (HTTP {resp.status_code})",
                    "platnik_vat": False,
                    "blad_polaczenia": True,
                    "komunikat_bledu": f"Odpowiedź serwera MF HTTP {resp.status_code}",
                    "zrodlo": "MF_BIALA_LISTA_ERROR"
                }

            data = resp.json()
            subject = data.get("result", {}).get("subject")
            if not subject:
                return {
                    "nip": clean_nip,
                    "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                    "platnik_vat": False,
                    "blad_polaczenia": False,
                    "zrodlo": "MF_BIALA_LISTA"
                }

            status_vat_raw = subject.get("statusVat") or ""
            status_vat = status_vat_raw.strip().lower()
            platnik_vat = (status_vat == "czynny")

            adres = subject.get("workingAddress") or subject.get("residenceAddress") or ""

            krs_val = subject.get("krs")
            krs = krs_val.strip() if krs_val else None

            nazwa = (subject.get("name") or "").strip()
            regon_val = subject.get("regon")
            regon = regon_val.strip() if regon_val else None

            return {
                "nip": clean_nip,
                "nazwa": nazwa,
                "regon": regon,
                "krs": krs,
                "adres": adres.strip() if adres else "",
                "status_vat": subject.get("statusVat", ""),
                "platnik_vat": platnik_vat,
                "rachunki_bankowe": subject.get("accountNumbers") or [],
                "zrodlo": "MF_BIALA_LISTA",
                "blad_polaczenia": False
            }
        except requests.RequestException as exc:
            # W środowisku offline lub przy braku sieci zwracamy jawny błąd połączenia
            return {
                "nip": clean_nip,
                "status_vat": "Brak połączenia z API MF (błąd sieci / offline)",
                "platnik_vat": False,
                "blad_polaczenia": True,
                "komunikat_bledu": f"Błąd połączenia z API MF: {exc.__class__.__name__}",
                "zrodlo": "MF_BIALA_LISTA_ERROR"
            }
        except Exception as exc:
            return {
                "nip": clean_nip,
                "status_vat": "Błąd zapytania do API MF",
                "platnik_vat": False,
                "blad_polaczenia": True,
                "komunikat_bledu": str(exc),
                "zrodlo": "MF_BIALA_LISTA_ERROR"
            }

    @classmethod
    def fetch_from_ceidg(cls, nip: str, api_token: Optional[str] = None, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Odpytuje oficjalną Hurtownię Danych CEIDG (dane.biznes.gov.pl) dla JDG.
        Wymaga darmowego klucza API (Authorization: Bearer <token>) z portalu dane.biznes.gov.pl.
        Zwraca: kody PKD (przeważające i pozostałe), status działalności.
        """
        clean_nip = cls.clean_nip(nip)
        token = api_token or os.getenv("CEIDG_API_TOKEN")
        if not token or not clean_nip:
            return None

        url = f"{cls.CEIDG_API_URL}?nip={clean_nip}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "TaxPilot_AI/1.0"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return None

            data = resp.json()
            firmy = data.get("firmy", [])
            if not firmy:
                return None

            wpis = firmy[0]
            pkd_list = wpis.get("pkd", [])
            pkd_glowny = wpis.get("pkdGlowny")
            if pkd_glowny and pkd_glowny not in pkd_list:
                pkd_list.insert(0, pkd_glowny)

            return {
                "nip": clean_nip,
                "nazwa": wpis.get("nazwa", ""),
                "kody_pkd": pkd_list,
                "pkd_glowny": pkd_glowny,
                "status": wpis.get("status", ""),
                "zrodlo": "CEIDG"
            }
        except Exception:
            return None

    @classmethod
    def fetch_company_info(cls, nip: str, ceidg_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Pobiera zintegrowane dane o firmie łącząc Białą Listę MF oraz CEIDG (jeśli dostępny token).
        Zapewnia fallback w przypadku braku połączenia lub braku tokena CEIDG.
        """
        clean_nip = cls.clean_nip(nip)
        res: Dict[str, Any] = {
            "nip": clean_nip,
            "nazwa": None,
            "adres": None,
            "regon": None,
            "platnik_vat": True,
            "kody_pkd": [],
            "zrodlo": []
        }

        # 1. Próba pobrania z Białej Listy MF (bezpłatna, bez tokena)
        mf_data = cls.fetch_from_mf_biala_lista(clean_nip)
        if mf_data and not mf_data.get("blad_polaczenia"):
            res["nazwa"] = mf_data.get("nazwa")
            res["adres"] = mf_data.get("adres")
            res["regon"] = mf_data.get("regon")
            res["krs"] = mf_data.get("krs")
            res["platnik_vat"] = mf_data.get("platnik_vat", True)
            res["rachunki_bankowe"] = mf_data.get("rachunki_bankowe", [])
            res["zrodlo"].append("MF_BIALA_LISTA")
        elif mf_data and mf_data.get("blad_polaczenia"):
            res["blad_polaczenia"] = True
            res["komunikat_bledu"] = mf_data.get("komunikat_bledu")

        # 2. Próba pobrania z CEIDG (jeśli jest token)
        ceidg_data = cls.fetch_from_ceidg(clean_nip, api_token=ceidg_token)
        if ceidg_data:
            if not res["nazwa"]:
                res["nazwa"] = ceidg_data.get("nazwa")
            res["kody_pkd"] = ceidg_data.get("kody_pkd", [])
            res["pkd_glowny"] = ceidg_data.get("pkd_glowny")
            res["zrodlo"].append("CEIDG")

        return res

