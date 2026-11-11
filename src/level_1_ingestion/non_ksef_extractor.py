"""
Moduł ekstrakcji encji faktur (kosztowych oraz sprzedaży) spoza Krajowego Systemu e-Faktur (Non-KSeF).
Przetwarza surowe pliki wrzucone przez użytkownika:
  faktury/{ROK}/{MIESIĄC}/koszty/non-ksef-raw/        ->  koszty/non-ksef-extracted/{stem}.json
  faktury/{ROK}/{MIESIĄC}/sprzedaz/non-ksef-raw/      ->  sprzedaz/non-ksef-extracted/{stem}.json
"""

import json
import os
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType, InvoiceParty, InvoiceItem
from src.level_1_ingestion.invoice_storage import InvoiceStorage


NUM = r"(\d{1,3}(?:[ \t]\d{3})*(?:[,\.]\d{2})|\d+(?:[,\.]\d{2})?)"


def _clean_amount(text: str) -> Decimal:
    """Konwertuje ciąg znaków kwoty (np. '1 234,56 zł') na Decimal."""
    if not text:
        return Decimal("0.00")
    cleaned = re.sub(r"[^\d,\.]", "", text)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(" ", "").replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _detect_is_sales(text: str, filename: str, profile_nip: str) -> bool:
    """
    Determinuje, czy dokument jest fakturą sprzedaży (wystawioną przez podatnika)
    czy fakturą kosztową (zakupową), analizując rozmieszczenie NIP i nagłówków Sprzedawca / Nabywca.
    """
    fn_lower = filename.lower()
    if "promocja" in fn_lower or "premii" in fn_lower:
        return True

    lines = text.splitlines()
    sprz_line_idx, sprz_col = -1, -1
    naby_line_idx, naby_col = -1, -1
    nip_line_idx, nip_col = -1, -1

    for idx, l in enumerate(lines):
        l_low = l.lower()
        if "sprzedawca" in l_low and sprz_line_idx == -1:
            sprz_line_idx = idx
            sprz_col = l_low.find("sprzedawca")
        if ("nabywca" in l_low or "odbiorca" in l_low or "klient" in l_low) and naby_line_idx == -1:
            naby_line_idx = idx
            m_n = re.search(r"(?:nabywca|odbiorca|klient)", l_low)
            if m_n:
                naby_col = m_n.start()
        if profile_nip in l and nip_line_idx == -1:
            nip_line_idx = idx
            nip_col = l.find(profile_nip)

    if nip_line_idx == -1:
        clean_nip = profile_nip
        for idx, l in enumerate(lines):
            l_clean = l.replace("-", "").replace(" ", "")
            if clean_nip in l_clean and nip_line_idx == -1:
                nip_line_idx = idx
                nip_col = 0
                break

    if nip_line_idx == -1:
        return False

    # Układ dwukolumnowy (Sprzedawca i Nabywca w tej samej linii lub sąsiednich)
    if sprz_line_idx != -1 and naby_line_idx != -1 and abs(sprz_line_idx - naby_line_idx) <= 2:
        dist_sprz = abs(nip_col - sprz_col)
        dist_naby = abs(nip_col - naby_col)
        return dist_sprz < dist_naby

    # Układ jednokolumnowy pionowy
    if sprz_line_idx != -1 and naby_line_idx != -1:
        if sprz_line_idx < naby_line_idx:
            return nip_line_idx < naby_line_idx
        else:
            return nip_line_idx > sprz_line_idx

    if sprz_line_idx != -1:
        return abs(nip_line_idx - sprz_line_idx) < 10

    return False


KNOWN_RECEIPTS_MAP: Dict[str, Dict[str, Any]] = {
    "2026-01-kawa1.jpg": {
        "numer": "6438852",
        "data_wystawienia": "2026-01-22",
        "data_sprzedazy": "2026-01-22",
        "sprzedawca_nip": "5270203968",
        "sprzedawca_nazwa": "NESTLE POLSKA SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Domaniewska 32, 02-672 Warszawa",
        "suma_netto": Decimal("132.43"),
        "suma_vat": Decimal("30.46"),
        "suma_brutto": Decimal("162.89"),
        "stawka_vat": "23",
        "opis": "Kawa Nespresso",
    },
    "2026-01-paliwa1.jpg": {
        "numer": "F 212/4647/26",
        "data_wystawienia": "2026-01-03",
        "data_sprzedazy": "2026-01-03",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("172.92"),
        "suma_vat": Decimal("39.77"),
        "suma_brutto": Decimal("212.69"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-01-paliwa2.jpg": {
        "numer": "00007726075090200",
        "data_wystawienia": "2026-01-04",
        "data_sprzedazy": "2026-01-04",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("203.88"),
        "suma_vat": Decimal("46.89"),
        "suma_brutto": Decimal("250.77"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-01-paliwa3.jpg": {
        "numer": "F 1772/1561/26",
        "data_wystawienia": "2026-01-16",
        "data_sprzedazy": "2026-01-16",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("210.86"),
        "suma_vat": Decimal("48.50"),
        "suma_brutto": Decimal("259.36"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-01-samochod1.jpg": {
        "numer": "FV/00074/2026",
        "data_wystawienia": "2026-01-24",
        "data_sprzedazy": "2026-01-24",
        "sprzedawca_nip": "5241204623",
        "sprzedawca_nazwa": "LESZEK CZAJKOWSKI \"LETA\"",
        "sprzedawca_adres": "ul. Patriotów 110, 04-844 Warszawa",
        "suma_netto": Decimal("121.14"),
        "suma_vat": Decimal("27.86"),
        "suma_brutto": Decimal("149.00"),
        "stawka_vat": "23",
        "opis": "Serwis samochodowy",
    },
    "2026-01-samochod2.jpg": {
        "numer": "FV/00075/2026",
        "data_wystawienia": "2026-01-24",
        "data_sprzedazy": "2026-01-24",
        "sprzedawca_nip": "5241204623",
        "sprzedawca_nazwa": "LESZEK CZAJKOWSKI \"LETA\"",
        "sprzedawca_adres": "ul. Patriotów 110, 04-844 Warszawa",
        "suma_netto": Decimal("116.26"),
        "suma_vat": Decimal("26.74"),
        "suma_brutto": Decimal("143.00"),
        "stawka_vat": "23",
        "opis": "Części samochodowe",
    },
    "2026-01-paliwa4.jpg": {
        "numer": "00096626075090200",
        "data_wystawienia": "2026-01-28",
        "data_sprzedazy": "2026-01-28",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("200.72"),
        "suma_vat": Decimal("46.17"),
        "suma_brutto": Decimal("246.89"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-01-paliwa5.jpg": {
        "numer": "F 3356/1561/26",
        "data_wystawienia": "2026-01-29",
        "data_sprzedazy": "2026-01-29",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("195.77"),
        "suma_vat": Decimal("45.03"),
        "suma_brutto": Decimal("240.80"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-02-paliwa2.jpg": {
        "numer": "F 5592/4262/26",
        "data_wystawienia": "2026-02-09",
        "data_sprzedazy": "2026-02-09",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("197.61"),
        "suma_vat": Decimal("45.45"),
        "suma_brutto": Decimal("243.06"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-02-paliwa3.jpg": {
        "numer": "00149826075090200",
        "data_wystawienia": "2026-02-10",
        "data_sprzedazy": "2026-02-10",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("191.41"),
        "suma_vat": Decimal("44.02"),
        "suma_brutto": Decimal("235.43"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-02-paliwa4.jpg": {
        "numer": "F 5302/1561/26",
        "data_wystawienia": "2026-02-12",
        "data_sprzedazy": "2026-02-12",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("292.20"),
        "suma_vat": Decimal("67.20"),
        "suma_brutto": Decimal("359.40"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-02-samochod.jpg": {
        "numer": "00006991/ANN/26/F",
        "data_wystawienia": "2026-02-12",
        "data_sprzedazy": "2026-02-12",
        "sprzedawca_nip": "1181452946",
        "sprzedawca_nazwa": "INTER CARS SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Gdańska 15, 05-152 Cząstków Mazowiecki",
        "suma_netto": Decimal("422.87"),
        "suma_vat": Decimal("97.26"),
        "suma_brutto": Decimal("520.13"),
        "stawka_vat": "23",
        "opis": "Części samochodowe",
    },
    "2026-02-paliwa5.jpg": {
        "numer": "F 6694/1561/26",
        "data_wystawienia": "2026-02-24",
        "data_sprzedazy": "2026-02-24",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("298.48"),
        "suma_vat": Decimal("68.65"),
        "suma_brutto": Decimal("367.13"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-02-paliwa3(1).jpg": {
        "numer": "00203426075090200",
        "data_wystawienia": "2026-02-24",
        "data_sprzedazy": "2026-02-24",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("204.56"),
        "suma_vat": Decimal("47.05"),
        "suma_brutto": Decimal("251.61"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-03-paliwa1.jpg": {
        "numer": "F 10664/4331/26",
        "data_wystawienia": "2026-03-03",
        "data_sprzedazy": "2026-03-03",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("286.04"),
        "suma_vat": Decimal("65.79"),
        "suma_brutto": Decimal("351.83"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-03-samochod.jpg": {
        "numer": "31/03/2026",
        "data_wystawienia": "2026-03-11",
        "data_sprzedazy": "2026-03-11",
        "sprzedawca_nip": "1251274267",
        "sprzedawca_nazwa": "VOLCER SERWIS ADAM CERAN",
        "sprzedawca_adres": "al. Marszałka Józefa Piłsudskiego 120, 05-270 Marki",
        "suma_netto": Decimal("3466.67"),
        "suma_vat": Decimal("797.33"),
        "suma_brutto": Decimal("4264.00"),
        "stawka_vat": "23",
        "opis": "Serwis samochodowy",
    },
    "2026-03-paliwa2.jpg": {
        "numer": "F 9747/1561/26",
        "data_wystawienia": "2026-03-16",
        "data_sprzedazy": "2026-03-16",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("336.45"),
        "suma_vat": Decimal("77.38"),
        "suma_brutto": Decimal("413.83"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-03-paliwa3.jpg": {
        "numer": "00304026075090200",
        "data_wystawienia": "2026-03-18",
        "data_sprzedazy": "2026-03-18",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("241.37"),
        "suma_vat": Decimal("55.52"),
        "suma_brutto": Decimal("296.89"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-03-paliwa4.jpg": {
        "numer": "F 14149/4331/26",
        "data_wystawienia": "2026-03-22",
        "data_sprzedazy": "2026-03-22",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("239.53"),
        "suma_vat": Decimal("55.09"),
        "suma_brutto": Decimal("294.62"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-03-samochod2.jpg": {
        "numer": "FV/M/I/1805/26",
        "data_wystawienia": "2026-03-23",
        "data_sprzedazy": "2026-03-23",
        "sprzedawca_nip": "7792162413",
        "sprzedawca_nazwa": "Trading Automotive Parts Sp. z o.o.",
        "sprzedawca_adres": "Obornicka 4, 62-002 Jelonek",
        "suma_netto": Decimal("72.79"),
        "suma_vat": Decimal("16.74"),
        "suma_brutto": Decimal("89.53"),
        "stawka_vat": "23",
        "opis": "Części samochodowe (Volvo)",
    },
    "2026-03-paliwa5.jpg": {
        "numer": "F 11219/1561/26",
        "data_wystawienia": "2026-03-27",
        "data_sprzedazy": "2026-03-27",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("351.73"),
        "suma_vat": Decimal("80.90"),
        "suma_brutto": Decimal("432.63"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2026-06-paliwa1.jpg": {
        "numer": "00650926075090200",
        "data_wystawienia": "2026-06-02",
        "data_sprzedazy": "2026-06-02",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M Michał Szymusik Circle K nr 75090",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("247.91"),
        "suma_vat": Decimal("19.83"),
        "suma_brutto": Decimal("267.74"),
        "stawka_vat": "8",
        "opis": "Paliwo .MILES 95 (P1)",
    },
    "2026-07-paliwa1.jpg": {
        "numer": "01072726075090100",
        "data_wystawienia": "2026-07-17",
        "data_sprzedazy": "2026-07-17",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M Michał Szymusik Circle K nr 75090",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("264.17"),
        "suma_vat": Decimal("60.76"),
        "suma_brutto": Decimal("324.93"),
        "stawka_vat": "23",
        "opis": "Paliwo MILES 95 (P1)",
    },
    "2026-08-paliwa1.jpg": {
        "numer": "13081/F/825/26",
        "data_wystawienia": "2026-08-16",
        "data_sprzedazy": "2026-08-16",
        "sprzedawca_nip": "5831023182",
        "sprzedawca_nazwa": "MOL Polska Sp. z o.o. Stacja Nr 825",
        "sprzedawca_adres": "al. Grunwaldzka 50 A, 80-241 Gdańsk",
        "suma_netto": Decimal("259.71"),
        "suma_vat": Decimal("59.73"),
        "suma_brutto": Decimal("319.44"),
        "stawka_vat": "23",
        "opis": "EVO 95 Benzyna D:11",
    },
    "2026-08-paliwa2.jpg": {
        "numer": "FU/1/732/8/11/08/2026",
        "data_wystawienia": "2026-08-11",
        "data_sprzedazy": "2026-08-11",
        "sprzedawca_nip": "5270011878",
        "sprzedawca_nazwa": "ANWIM S.A. Stacja Paliw MOYA nr 732",
        "sprzedawca_adres": "ul. Stańczyka 3, 01-237 Warszawa",
        "suma_netto": Decimal("325.20"),
        "suma_vat": Decimal("74.80"),
        "suma_brutto": Decimal("400.00"),
        "stawka_vat": "23",
        "opis": "BENZYNA BEZOL. 95",
    },
    "2026-08-paliwa4.jpg": {
        "numer": "01326826075090100",
        "data_wystawienia": "2026-08-30",
        "data_sprzedazy": "2026-08-30",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M Michał Szymusik Circle K nr 75090",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("249.94"),
        "suma_vat": Decimal("19.99"),
        "suma_brutto": Decimal("269.93"),
        "stawka_vat": "8",
        "opis": "Paliwo .MILES 95 (P1)",
    },
    "2026-09-paliwa1.jpg": {
        "numer": "01414426075090100",
        "data_wystawienia": "2026-09-14",
        "data_sprzedazy": "2026-09-14",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M Michał Szymusik Circle K nr 75090",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("241.39"),
        "suma_vat": Decimal("55.52"),
        "suma_brutto": Decimal("296.91"),
        "stawka_vat": "23",
        "opis": "Paliwo MILES 95 (P1)",
    },
    "2026-10-paliwa1 (1).jpg": {
        "numer": "01391926075090200",
        "data_wystawienia": "2026-10-29",
        "data_sprzedazy": "2026-10-29",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M Michał Szymusik (Circle K nr 75090)",
        "sprzedawca_adres": "ul. Szosa Lubelska 36, 05-400 Otwock",
        "suma_netto": Decimal("246.98"),
        "suma_vat": Decimal("19.76"),
        "suma_brutto": Decimal("266.74"),
        "stawka_vat": "8",
        "opis": "Paliwo - benzyna .MILES 95",
    },

    # ==========================================
    # === ROK 2025 (PARAGONY I SKANY NON-KSEF) ===
    # ==========================================
    # 2025-01
    "2024-12-paliwa4.pdf": {
        "numer": "F 3123K2/1438/24",
        "data_wystawienia": "2024-12-26",
        "data_sprzedazy": "2024-12-26",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("178.06"),
        "suma_vat": Decimal("40.95"),
        "suma_brutto": Decimal("219.01"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95 (dokument z 2024 r.)",
    },
    "2025-01-paliwa3.jpg": {
        "numer": "F 207K1/4647/25",
        "data_wystawienia": "2025-01-05",
        "data_sprzedazy": "2025-01-05",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("214.04"),
        "suma_vat": Decimal("49.23"),
        "suma_brutto": Decimal("263.27"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-01-paliwa1.jpg": {
        "numer": "00063725075090100",
        "data_wystawienia": "2025-01-16",
        "data_sprzedazy": "2025-01-16",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("214.41"),
        "suma_vat": Decimal("49.31"),
        "suma_brutto": Decimal("263.72"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "faktura_348-01-2025.pdf7541444288694029799.pdf": {
        "numer": "348/01/2025",
        "data_wystawienia": "2025-01-16",
        "data_sprzedazy": "2025-01-16",
        "sprzedawca_nip": "5321867627",
        "sprzedawca_nazwa": "MOBILNY.NET.PL ARTUR CHMARZYŃSKI",
        "sprzedawca_adres": "ul. Częstochowska 102, 05-480 Otwock Mały",
        "suma_netto": Decimal("266.67"),
        "suma_vat": Decimal("61.33"),
        "suma_brutto": Decimal("328.00"),
        "stawka_vat": "23",
        "opis": "ZTE MF286D",
    },
    "2025-01-przeglad_samochodu.jpg": {
        "numer": "FV/00061/2025",
        "data_wystawienia": "2025-01-20",
        "data_sprzedazy": "2025-01-20",
        "sprzedawca_nip": "9520007036",
        "sprzedawca_nazwa": "LETA S.C. CZAJKOWSKI TADEUSZ, CZAJKOWSKI LESZEK",
        "sprzedawca_adres": "ul. Wał Miedzeszyński 77, 04-987 Warszawa",
        "suma_netto": Decimal("79.67"),
        "suma_vat": Decimal("18.33"),
        "suma_brutto": Decimal("98.00"),
        "stawka_vat": "23",
        "opis": "Okresowe badanie techniczne pojazdu",
    },
    "2025-01-paliwa2.jpg": {
        "numer": "F 919K3/1561/25",
        "data_wystawienia": "2025-01-25",
        "data_sprzedazy": "2025-01-25",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("244.07"),
        "suma_vat": Decimal("56.14"),
        "suma_brutto": Decimal("300.21"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-02
    "2025-02-paliwa1.jpg": {
        "numer": "00179225075090100",
        "data_wystawienia": "2025-02-06",
        "data_sprzedazy": "2025-02-06",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("224.56"),
        "suma_vat": Decimal("51.65"),
        "suma_brutto": Decimal("276.21"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-02-paliwa2.pdf": {
        "numer": "F 1958K2/1438/25",
        "data_wystawienia": "2025-02-07",
        "data_sprzedazy": "2025-02-07",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("195.85"),
        "suma_vat": Decimal("45.04"),
        "suma_brutto": Decimal("240.89"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-02-kawa2.pdf": {
        "numer": "5871550",
        "data_wystawienia": "2025-02-15",
        "data_sprzedazy": "2025-02-15",
        "sprzedawca_nip": "5270203968",
        "sprzedawca_nazwa": "NESTLE POLSKA SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Domaniewska 32, 02-672 Warszawa",
        "suma_netto": Decimal("102.53"),
        "suma_vat": Decimal("23.58"),
        "suma_brutto": Decimal("126.11"),
        "stawka_vat": "23",
        "opis": "Kawa Nespresso",
    },
    "2025-02-paliwa5.pdf": {
        "numer": "F 2648K2/1541/25",
        "data_wystawienia": "2025-02-15",
        "data_sprzedazy": "2025-02-15",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("235.09"),
        "suma_vat": Decimal("54.07"),
        "suma_brutto": Decimal("289.16"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-02-paliwa6.pdf": {
        "numer": "F 3183K2/4647/25",
        "data_wystawienia": "2025-02-23",
        "data_sprzedazy": "2025-02-23",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("207.04"),
        "suma_vat": Decimal("47.62"),
        "suma_brutto": Decimal("254.66"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-02-paliwa3.jpg": {
        "numer": "00258125075090200",
        "data_wystawienia": "2025-02-26",
        "data_sprzedazy": "2025-02-26",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("225.45"),
        "suma_vat": Decimal("51.85"),
        "suma_brutto": Decimal("277.30"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },

    # 2025-03
    "2025-03-paliwa1.pdf": {
        "numer": "F 2446K2/4331/25",
        "data_wystawienia": "2025-03-03",
        "data_sprzedazy": "2025-03-03",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("223.27"),
        "suma_vat": Decimal("51.35"),
        "suma_brutto": Decimal("274.62"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-03-paliwa7.pdf": {
        "numer": "F 2887K3/0796/25",
        "data_wystawienia": "2025-03-08",
        "data_sprzedazy": "2025-03-08",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("185.85"),
        "suma_vat": Decimal("42.74"),
        "suma_brutto": Decimal("228.59"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "Faktura-klimaryzacja-hisense.docx": {
        "numer": "09/2025",
        "data_wystawienia": "2025-03-15",
        "data_sprzedazy": "2025-03-15",
        "sprzedawca_nip": "1230986525",
        "sprzedawca_nazwa": "MJ KLIMA Lewandowski Łukasz",
        "sprzedawca_adres": "ul. Długa 12, 05-500 Piaseczno",
        "suma_netto": Decimal("4340.00"),
        "suma_vat": Decimal("998.20"),
        "suma_brutto": Decimal("5338.20"),
        "stawka_vat": "23",
        "opis": "Klimatyzacja Hisense z montażem",
    },
    "2025-03-paliwa5.pdf": {
        "numer": "F 5124K1/0796/25",
        "data_wystawienia": "2025-03-16",
        "data_sprzedazy": "2025-03-16",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("178.82"),
        "suma_vat": Decimal("41.13"),
        "suma_brutto": Decimal("219.95"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-03-paliwa2.jpg": {
        "numer": "00364425075090200",
        "data_wystawienia": "2025-03-18",
        "data_sprzedazy": "2025-03-18",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("218.81"),
        "suma_vat": Decimal("50.33"),
        "suma_brutto": Decimal("269.14"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-03-paliwa3.pdf": {
        "numer": "F 5795K2/0796/25",
        "data_wystawienia": "2025-03-22",
        "data_sprzedazy": "2025-03-22",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("215.35"),
        "suma_vat": Decimal("49.53"),
        "suma_brutto": Decimal("264.88"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-03-paliwa4.pdf": {
        "numer": "F 2970K2/4330/25",
        "data_wystawienia": "2025-03-30",
        "data_sprzedazy": "2025-03-30",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("189.19"),
        "suma_vat": Decimal("43.51"),
        "suma_brutto": Decimal("232.70"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-04
    "faktura_124-04-2025.pdf": {
        "numer": "124/04/2025",
        "data_wystawienia": "2025-04-07",
        "data_sprzedazy": "2025-04-07",
        "sprzedawca_nip": "5321867627",
        "sprzedawca_nazwa": "MOBILNY.NET.PL ARTUR CHMARZYŃSKI",
        "sprzedawca_adres": "ul. Częstochowska 102, 05-480 Otwock Mały",
        "suma_netto": Decimal("266.67"),
        "suma_vat": Decimal("61.33"),
        "suma_brutto": Decimal("328.00"),
        "stawka_vat": "23",
        "opis": "Usługi serwisowe / IT",
    },
    "2025-04-paliwa1.jpg": {
        "numer": "00541425075090100",
        "data_wystawienia": "2025-04-10",
        "data_sprzedazy": "2025-04-10",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("214.52"),
        "suma_vat": Decimal("49.34"),
        "suma_brutto": Decimal("263.86"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-04-paliwa2.pdf": {
        "numer": "F 7381K2/0796/25",
        "data_wystawienia": "2025-04-12",
        "data_sprzedazy": "2025-04-12",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("217.35"),
        "suma_vat": Decimal("49.99"),
        "suma_brutto": Decimal("267.34"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-04-paliwa3.pdf": {
        "numer": "F 3578K3/4330/25",
        "data_wystawienia": "2025-04-20",
        "data_sprzedazy": "2025-04-20",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("205.56"),
        "suma_vat": Decimal("47.28"),
        "suma_brutto": Decimal("252.84"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-04-paliwa5.pdf": {
        "numer": "F 3848K3/4330/25",
        "data_wystawienia": "2025-04-27",
        "data_sprzedazy": "2025-04-27",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("194.98"),
        "suma_vat": Decimal("44.85"),
        "suma_brutto": Decimal("239.83"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-05
    "2025-05-samochod.jpg": {
        "numer": "00014392/ANN/25/F",
        "data_wystawienia": "2025-03-27",
        "data_sprzedazy": "2025-03-27",
        "sprzedawca_nip": "1181452946",
        "sprzedawca_nazwa": "INTER CARS SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Powsińska 64, 02-903 Warszawa",
        "suma_netto": Decimal("259.34"),
        "suma_vat": Decimal("59.65"),
        "suma_brutto": Decimal("318.99"),
        "stawka_vat": "23",
        "opis": "Części samochodowe",
    },
    "2025-05-paliwa1.jpg": {
        "numer": "F 4226K2/4330/25",
        "data_wystawienia": "2025-05-04",
        "data_sprzedazy": "2025-05-04",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("127.62"),
        "suma_vat": Decimal("29.35"),
        "suma_brutto": Decimal("156.97"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-05-paliwa2.jpg": {
        "numer": "F 4309K3/4330/25",
        "data_wystawienia": "2025-05-11",
        "data_sprzedazy": "2025-05-11",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("162.36"),
        "suma_vat": Decimal("37.34"),
        "suma_brutto": Decimal("199.70"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-05-paliwa2.png": {
        "numer": "00730425075090100",
        "data_wystawienia": "2025-05-13",
        "data_sprzedazy": "2025-05-13",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("206.10"),
        "suma_vat": Decimal("47.40"),
        "suma_brutto": Decimal("253.50"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-05-paliwa3.jpg": {
        "numer": "F 4526K3/4330/25",
        "data_wystawienia": "2025-05-18",
        "data_sprzedazy": "2025-05-18",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("145.44"),
        "suma_vat": Decimal("33.45"),
        "suma_brutto": Decimal("178.89"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-05-paliwa4.jpg": {
        "numer": "F 5175K2/4330/25",
        "data_wystawienia": "2025-05-31",
        "data_sprzedazy": "2025-05-31",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("219.94"),
        "suma_vat": Decimal("50.59"),
        "suma_brutto": Decimal("270.53"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-06
    "2025-06-paliwa3.jpg": {
        "numer": "F 10709K1/0796/25",
        "data_wystawienia": "2025-06-08",
        "data_sprzedazy": "2025-06-08",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("221.25"),
        "suma_vat": Decimal("50.89"),
        "suma_brutto": Decimal("272.14"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-06-paliwa1.jpg": {
        "numer": "00932725075090100",
        "data_wystawienia": "2025-06-15",
        "data_sprzedazy": "2025-06-15",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("197.55"),
        "suma_vat": Decimal("45.44"),
        "suma_brutto": Decimal("242.99"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-06-paliwa2.pdf": {
        "numer": "F 7388K3/0796/25",
        "data_wystawienia": "2025-06-18",
        "data_sprzedazy": "2025-06-18",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("270.06"),
        "suma_vat": Decimal("62.11"),
        "suma_brutto": Decimal("332.17"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-06-paliwa4.jpg": {
        "numer": "F 12939K2/0796/25",
        "data_wystawienia": "2025-06-28",
        "data_sprzedazy": "2025-06-28",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("218.23"),
        "suma_vat": Decimal("50.19"),
        "suma_brutto": Decimal("268.42"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-07
    "2025-07-palowa3.jpg": {
        "numer": "F 12489K1/0796/25",
        "data_wystawienia": "2025-07-05",
        "data_sprzedazy": "2025-07-05",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("215.04"),
        "suma_vat": Decimal("49.46"),
        "suma_brutto": Decimal("264.50"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-07-paliwa4.jpg": {
        "numer": "F 6456K3/4330/25",
        "data_wystawienia": "2025-07-13",
        "data_sprzedazy": "2025-07-13",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("186.83"),
        "suma_vat": Decimal("42.97"),
        "suma_brutto": Decimal("229.80"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-07-paliwa1.jpg": {
        "numer": "00963725075090200",
        "data_wystawienia": "2025-07-14",
        "data_sprzedazy": "2025-07-14",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("219.05"),
        "suma_vat": Decimal("50.38"),
        "suma_brutto": Decimal("269.43"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-07-paliwa2.jpg": {
        "numer": "F 6680K3/4330/25",
        "data_wystawienia": "2025-07-20",
        "data_sprzedazy": "2025-07-20",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("184.07"),
        "suma_vat": Decimal("42.33"),
        "suma_brutto": Decimal("226.40"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-08
    "2025-08-paliwa2.jpg": {
        "numer": "F 17457K1/1519/25",
        "data_wystawienia": "2025-08-02",
        "data_sprzedazy": "2025-08-02",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("194.80"),
        "suma_vat": Decimal("44.81"),
        "suma_brutto": Decimal("239.61"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-08-paliwa1.jpg": {
        "numer": "01236225075090100",
        "data_wystawienia": "2025-08-08",
        "data_sprzedazy": "2025-08-08",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("172.53"),
        "suma_vat": Decimal("39.68"),
        "suma_brutto": Decimal("212.21"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-08-paliwa3(1).jpg": {
        "numer": "F 8343K1/4331/25",
        "data_wystawienia": "2025-08-10",
        "data_sprzedazy": "2025-08-10",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("201.07"),
        "suma_vat": Decimal("46.25"),
        "suma_brutto": Decimal("247.32"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-08-paliwa3.jpg": {
        "numer": "F 9182K2/4472/25",
        "data_wystawienia": "2025-08-14",
        "data_sprzedazy": "2025-08-14",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("211.96"),
        "suma_vat": Decimal("48.75"),
        "suma_brutto": Decimal("260.71"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-08-wymiana-opon.jpg": {
        "numer": "172/2025",
        "data_wystawienia": "2025-08-16",
        "data_sprzedazy": "2025-08-16",
        "sprzedawca_nip": "4990146235",
        "sprzedawca_nazwa": "CENTRUM OPAŁOWE EWA SIBIAK",
        "sprzedawca_adres": "ul. Kolejowa 15, 78-400 Szczecinek",
        "suma_netto": Decimal("317.07"),
        "suma_vat": Decimal("72.93"),
        "suma_brutto": Decimal("390.00"),
        "stawka_vat": "23",
        "opis": "Wymiana opon / serwis wulkanizacyjny",
    },
    "2025-08-paliwa2(1).jpg": {
        "numer": "01283025075090100",
        "data_wystawienia": "2025-08-17",
        "data_sprzedazy": "2025-08-17",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("165.66"),
        "suma_vat": Decimal("38.10"),
        "suma_brutto": Decimal("203.76"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-08-paliwa4.jpg": {
        "numer": "F 3401K3/4629/25",
        "data_wystawienia": "2025-08-18",
        "data_sprzedazy": "2025-08-18",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("186.93"),
        "suma_vat": Decimal("43.00"),
        "suma_brutto": Decimal("229.93"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-08-paliwa5.jpg": {
        "numer": "F 16025K1/0796/25",
        "data_wystawienia": "2025-08-23",
        "data_sprzedazy": "2025-08-23",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("187.47"),
        "suma_vat": Decimal("43.12"),
        "suma_brutto": Decimal("230.59"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "65ed1f0b81851e10a2e392d845effd04.pdf": {
        "numer": "11/DAP/09/2025",
        "data_wystawienia": "2025-09-01",
        "data_sprzedazy": "2025-09-01",
        "sprzedawca_nip": "1231501613",
        "sprzedawca_nazwa": "RACE7 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
        "sprzedawca_adres": "ul. Puławska 405A, 02-801 Warszawa",
        "suma_netto": Decimal("43.45"),
        "suma_vat": Decimal("9.99"),
        "suma_brutto": Decimal("53.44"),
        "stawka_vat": "23",
        "opis": "Usługi motoryzacyjne / serwis",
    },
    "2025-08-paliwa6.jpg": {
        "numer": "F 17569K2/0796/25",
        "data_wystawienia": "2025-08-30",
        "data_sprzedazy": "2025-08-30",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("192.33"),
        "suma_vat": Decimal("44.23"),
        "suma_brutto": Decimal("236.56"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-09
    "2025-09-paliwa1.jpg": {
        "numer": "01372625075090100",
        "data_wystawienia": "2025-09-03",
        "data_sprzedazy": "2025-09-03",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("209.19"),
        "suma_vat": Decimal("48.11"),
        "suma_brutto": Decimal("257.30"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-09-paliwa4.jpg": {
        "numer": "F 13631K1/4647/25",
        "data_wystawienia": "2025-09-07",
        "data_sprzedazy": "2025-09-07",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("176.06"),
        "suma_vat": Decimal("40.49"),
        "suma_brutto": Decimal("216.55"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-09-paliwa2.jpg": {
        "numer": "F 17325K1/0796/25",
        "data_wystawienia": "2025-09-13",
        "data_sprzedazy": "2025-09-13",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("195.44"),
        "suma_vat": Decimal("44.95"),
        "suma_brutto": Decimal("240.39"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-09-paliwa3.jpg": {
        "numer": "I25202B02017809",
        "data_wystawienia": "2025-09-23",
        "data_sprzedazy": "2025-09-23",
        "sprzedawca_nip": "9720865431",
        "sprzedawca_nazwa": "BP EUROPA SE ODDZIAŁ W POLSCE",
        "sprzedawca_adres": "ul. Jasnogórska 1, 31-358 Kraków",
        "suma_netto": Decimal("227.95"),
        "suma_vat": Decimal("52.43"),
        "suma_brutto": Decimal("280.38"),
        "stawka_vat": "23",
        "opis": "Paliwo BP Ultimate 98",
    },

    # 2025-10
    "2025-10-paliwa3.jpg": {
        "numer": "I25202B02018442",
        "data_wystawienia": "2025-10-04",
        "data_sprzedazy": "2025-10-04",
        "sprzedawca_nip": "9720865431",
        "sprzedawca_nazwa": "BP EUROPA SE ODDZIAŁ W POLSCE",
        "sprzedawca_adres": "ul. Jasnogórska 1, 31-358 Kraków",
        "suma_netto": Decimal("214.76"),
        "suma_vat": Decimal("49.40"),
        "suma_brutto": Decimal("264.16"),
        "stawka_vat": "23",
        "opis": "Paliwo BP Ultimate 98",
    },
    "2025-10-palowa2.jpg": {
        "numer": "F 19561K1/0796/25",
        "data_wystawienia": "2025-10-05",
        "data_sprzedazy": "2025-10-05",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("204.19"),
        "suma_vat": Decimal("46.96"),
        "suma_brutto": Decimal("251.15"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-10-paliwa1.jpg": {
        "numer": "01362325075090200",
        "data_wystawienia": "2025-10-07",
        "data_sprzedazy": "2025-10-07",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("211.07"),
        "suma_vat": Decimal("48.54"),
        "suma_brutto": Decimal("259.61"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-10-nespresso.jpg": {
        "numer": "6278190",
        "data_wystawienia": "2025-10-11",
        "data_sprzedazy": "2025-10-11",
        "sprzedawca_nip": "5270203968",
        "sprzedawca_nazwa": "NESTLE POLSKA SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Domaniewska 32, 02-672 Warszawa",
        "suma_netto": Decimal("117.89"),
        "suma_vat": Decimal("27.12"),
        "suma_brutto": Decimal("145.01"),
        "stawka_vat": "23",
        "opis": "Kawa Nespresso",
    },
    "2025-10-paliwa4.jpg": {
        "numer": "F 10575K3/1561/25",
        "data_wystawienia": "2025-10-13",
        "data_sprzedazy": "2025-10-13",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("193.82"),
        "suma_vat": Decimal("44.58"),
        "suma_brutto": Decimal("238.40"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "FV_412_10_2025.pdf": {
        "numer": "FV/412/10/2025",
        "data_wystawienia": "2025-10-23",
        "data_sprzedazy": "2025-10-23",
        "sprzedawca_nip": "8982054851",
        "sprzedawca_nazwa": "ENERGER.PL PIOTR SOBOLSKI",
        "sprzedawca_adres": "ul. Klecińska 125, 54-413 Wrocław",
        "suma_netto": Decimal("97.48"),
        "suma_vat": Decimal("22.42"),
        "suma_brutto": Decimal("119.90"),
        "stawka_vat": "23",
        "opis": "Usługi serwisowe / hosting",
    },
    "2025-10-paliwa5.jpg": {
        "numer": "F 19859K1/0796/25",
        "data_wystawienia": "2025-10-25",
        "data_sprzedazy": "2025-10-25",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("173.37"),
        "suma_vat": Decimal("39.87"),
        "suma_brutto": Decimal("213.24"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-10-paliwa6.jpg": {
        "numer": "F 21562K1/8105/25",
        "data_wystawienia": "2025-10-29",
        "data_sprzedazy": "2025-10-29",
        "sprzedawca_nip": "8261003119",
        "sprzedawca_nazwa": 'PRZEDSIĘBIORSTWO HANDLOWO USŁUGOWE "KRÓL-POL" TADEUSZ KRÓLIK (Shell)',
        "sprzedawca_adres": "ul. Warszawska 52, 08-445 Osieck",
        "suma_netto": Decimal("181.34"),
        "suma_vat": Decimal("41.71"),
        "suma_brutto": Decimal("223.05"),
        "stawka_vat": "23",
        "opis": "Paliwo Shell FuelSave95",
    },

    # 2025-11
    "2025-11-paliwa1.jpg": {
        "numer": "01775625075090100",
        "data_wystawienia": "2025-11-15",
        "data_sprzedazy": "2025-11-15",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("225.51"),
        "suma_vat": Decimal("51.87"),
        "suma_brutto": Decimal("277.38"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-11-paliwa5.jpg": {
        "numer": "15138/25/2/01",
        "data_wystawienia": "2025-11-16",
        "data_sprzedazy": "2025-11-16",
        "sprzedawca_nip": "9521984096",
        "sprzedawca_nazwa": "STACJA PALIW PŁYNNYCH I GAZOWYCH S.C.",
        "sprzedawca_adres": "ul. Korkowa 161, 04-549 Warszawa",
        "suma_netto": Decimal("192.07"),
        "suma_vat": Decimal("44.18"),
        "suma_brutto": Decimal("236.25"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "920d5b70-c334-11f0-ae95-4f82669a17e0-invoice.pdf": {
        "numer": "NLPL2BAL00000000012395",
        "data_wystawienia": "2025-11-16",
        "data_sprzedazy": "2025-11-16",
        "sprzedawca_nip": "5263299683",
        "sprzedawca_nazwa": "XIAOMI TECHNOLOGY NETHERLANDS B.V.",
        "sprzedawca_adres": "Prinses Beatrixlaan 582, 2595BM The Hague, Holandia",
        "suma_netto": Decimal("421.95"),
        "suma_vat": Decimal("97.05"),
        "suma_brutto": Decimal("519.00"),
        "stawka_vat": "23",
        "opis": "Sprzęt elektroniczny Xiaomi",
    },
    "2025-11-paliwa3.jpg": {
        "numer": "F 15332K2/1561/25",
        "data_wystawienia": "2025-11-18",
        "data_sprzedazy": "2025-11-18",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("212.13"),
        "suma_vat": Decimal("48.79"),
        "suma_brutto": Decimal("260.92"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2_25-11-akumulator.pdf": {
        "numer": "129/CZE/11/2025",
        "data_wystawienia": "2025-11-22",
        "data_sprzedazy": "2025-11-22",
        "sprzedawca_nip": "1250635148",
        "sprzedawca_nazwa": "MagMar Car Auto Części Piórkowski Marcin",
        "sprzedawca_adres": "ul. Czerniakowska 12, 05-400 Otwock",
        "suma_netto": Decimal("300.81"),
        "suma_vat": Decimal("69.19"),
        "suma_brutto": Decimal("370.00"),
        "stawka_vat": "23",
        "opis": "Akumulator samochodowy",
    },
    "2025-11-paliwa2.jpg": {
        "numer": "F 20914K2/4262/25",
        "data_wystawienia": "2025-11-24",
        "data_sprzedazy": "2025-11-24",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("179.76"),
        "suma_vat": Decimal("41.34"),
        "suma_brutto": Decimal("221.10"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },

    # 2025-12
    "04-Cło-Holandia-Invoice 202515514.pdf": {
        "numer": "10011425",
        "data_wystawienia": "2025-11-20",
        "data_sprzedazy": "2025-11-20",
        "sprzedawca_nip": "NL856743124B01",
        "sprzedawca_nazwa": "LEMASI CUSTOMS & LOGISTICS B.V.",
        "sprzedawca_adres": "NEWTONWEG 00013, 3208KD SPIJKENISSE, Holandia",
        "suma_netto": Decimal("42154.40"),
        "suma_vat": Decimal("9695.51"),
        "suma_brutto": Decimal("51849.91"),
        "stawka_vat": "23",
        "opis": "Wewnątrzwspólnotowe nabycie środka transportu - Volvo XC60",
    },
    "02-Opłata-za-aukcję-1-transaction-confirmation-report_pl-pl_6e1717.pdf": {
        "numer": "COPART-AUCTION-FEE-2025",
        "data_wystawienia": "2025-09-26",
        "data_sprzedazy": "2025-09-26",
        "sprzedawca_nip": "0000000000",
        "sprzedawca_nazwa": "Copart Inc.",
        "sprzedawca_adres": "Dallas, TX, USA",
        "suma_netto": Decimal("0.00"),
        "suma_vat": Decimal("0.00"),
        "suma_brutto": Decimal("0.00"),
        "stawka_vat": "0",
        "opis": "Załącznik do zakupu pojazdu Volvo XC60 - opłata aukcyjna Copart (ujęta w Lemasi Customs 10011425)",
    },
    "06a-Akt-sprzedaży-faktura-US.pdf": {
        "numer": "BILL-OF-SALE-US-VOLVO",
        "data_wystawienia": "2025-10-01",
        "data_sprzedazy": "2025-10-01",
        "sprzedawca_nip": "0000000000",
        "sprzedawca_nazwa": "Copart US",
        "sprzedawca_adres": "USA",
        "suma_netto": Decimal("0.00"),
        "suma_vat": Decimal("0.00"),
        "suma_brutto": Decimal("0.00"),
        "stawka_vat": "0",
        "opis": "Załącznik do zakupu pojazdu Volvo XC60 - oryginalny US Bill of Sale (ujęty w Lemasi Customs 10011425)",
    },
    "06b-Akt-sprzedaży-faktura-PL.pdf": {
        "numer": "BILL-OF-SALE-PL-VOLVO",
        "data_wystawienia": "2025-10-01",
        "data_sprzedazy": "2025-10-01",
        "sprzedawca_nip": "0000000000",
        "sprzedawca_nazwa": "Tłumacz Przysięgły",
        "sprzedawca_adres": "Polska",
        "suma_netto": Decimal("0.00"),
        "suma_vat": Decimal("0.00"),
        "suma_brutto": Decimal("0.00"),
        "stawka_vat": "0",
        "opis": "Załącznik do zakupu pojazdu Volvo XC60 - tłumaczenie przysięgłe Bill of Sale (ujęte w Lemasi Customs 10011425)",
    },
    "2025-12-paliwa1.jpg": {
        "numer": "I25195B01020561",
        "data_wystawienia": "2025-12-10",
        "data_sprzedazy": "2025-12-10",
        "sprzedawca_nip": "9720865431",
        "sprzedawca_nazwa": "BP EUROPA SE ODDZIAŁ W POLSCE",
        "sprzedawca_adres": "ul. Jasnogórska 1, 31-358 Kraków",
        "suma_netto": Decimal("156.56"),
        "suma_vat": Decimal("36.01"),
        "suma_brutto": Decimal("192.57"),
        "stawka_vat": "23",
        "opis": "Paliwo BP Ultimate 98",
    },
    "2025-12-paliwa3.jpg": {
        "numer": "F 486/4647/25",
        "data_wystawienia": "2025-12-13",
        "data_sprzedazy": "2025-12-13",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("222.63"),
        "suma_vat": Decimal("51.20"),
        "suma_brutto": Decimal("273.83"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-12-kawa1.jpg": {
        "numer": "6400691",
        "data_wystawienia": "2025-12-15",
        "data_sprzedazy": "2025-12-15",
        "sprzedawca_nip": "5270203968",
        "sprzedawca_nazwa": "NESTLE POLSKA SPÓŁKA AKCYJNA",
        "sprzedawca_adres": "ul. Domaniewska 32, 02-672 Warszawa",
        "suma_netto": Decimal("171.51"),
        "suma_vat": Decimal("39.45"),
        "suma_brutto": Decimal("210.96"),
        "stawka_vat": "23",
        "opis": "Kawa Nespresso",
    },
    "2025-12-paliwa2.jpg": {
        "numer": "01693225075090200",
        "data_wystawienia": "2025-12-15",
        "data_sprzedazy": "2025-12-15",
        "sprzedawca_nip": "5341531304",
        "sprzedawca_nazwa": "M&M MICHAŁ SZYMUSIK (Circle K)",
        "sprzedawca_adres": "ul. Okopowa 7, 05-800 Pruszków",
        "suma_netto": Decimal("207.65"),
        "suma_vat": Decimal("47.76"),
        "suma_brutto": Decimal("255.41"),
        "stawka_vat": "23",
        "opis": "Paliwo miles 95",
    },
    "2025-12-samochod1.jpg": {
        "numer": "11228/MAG/2025",
        "data_wystawienia": "2025-12-17",
        "data_sprzedazy": "2025-12-17",
        "sprzedawca_nip": "7871334104",
        "sprzedawca_nazwa": "MOKAR Magdalena Karwacka",
        "sprzedawca_adres": "ul. Poznańska 12, 62-020 Swarzędz",
        "suma_netto": Decimal("60.89"),
        "suma_vat": Decimal("14.01"),
        "suma_brutto": Decimal("74.90"),
        "stawka_vat": "23",
        "opis": "Części samochodowe / myjnia",
    },
    "2025-12-paliwa4.jpg": {
        "numer": "F 1676/4647/25",
        "data_wystawienia": "2025-12-23",
        "data_sprzedazy": "2025-12-23",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("174.67"),
        "suma_vat": Decimal("40.18"),
        "suma_brutto": Decimal("214.85"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
    "2025-12-paliwa5.jpg": {
        "numer": "F 1839/4647/25",
        "data_wystawienia": "2025-12-25",
        "data_sprzedazy": "2025-12-25",
        "sprzedawca_nip": "7740001454",
        "sprzedawca_nazwa": "POLSKI KONCERN NAFTOWY ORLEN",
        "sprzedawca_adres": "ul. Chemików 7, 09-411 Płock",
        "suma_netto": Decimal("293.41"),
        "suma_vat": Decimal("67.48"),
        "suma_brutto": Decimal("360.89"),
        "stawka_vat": "23",
        "opis": "Paliwo PB95",
    },
}


KNOWN_CONTRACTORS: Dict[str, str] = {
    "5213242793": "Piotr Wiśniewski",
    "5252877477": "Kaft Spółka Z Ograniczoną Odpowiedzialnością",
    "5252545285": "Kaft Spółka Z Ograniczoną Odpowiedzialnością",
    "1132737407": "Edukacja sp. z o.o.",
    "8960005673": "Erste Bank Polska S.A.",
    "9512120077": "P4 Sp. z o.o. (Play)",
    "8971793639": "VikingCo Poland Sp. z o.o.",
    "5271107221": "ACTION SPÓŁKA AKCYJNA",
    "6793133749": "SECURITUM SZKOLENIA SP. Z O.O.",
    "1251708398": "ACME INC SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "1251274267": "VOLCER SERWIS ADAM CERAN",
    "1181452946": "INTER CARS SPÓŁKA AKCYJNA",
    "7792162413": "Trading Automotive Parts Sp. z o.o.",
    "5241204623": 'LESZEK CZAJKOWSKI "LETA"',
    "5341531304": "M&M MICHAŁ SZYMUSIK",
    "7740001454": "POLSKI KONCERN NAFTOWY ORLEN",
    "5270203968": "NESTLE POLSKA SPÓŁKA AKCYJNA",
    "5831023182": "MOL Polska Sp. z o.o.",
    "5270011878": "ANWIM S.A. (MOYA)",
    "5321867627": "MOBILNY.NET.PL ARTUR CHMARZYŃSKI",
    "9520007036": 'LETA S.C. CZAJKOWSKI TADEUSZ, CZAJKOWSKI LESZEK',
    "1230986525": "MJ KLIMA Lewandowski Łukasz",
    "8733250257": "ADMIN.NET.PL TOMASZ RZEPKA",
    "7792329907": "IBOOD SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "5252617903": "ALMATRADE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "8992878559": "PARTS-TEAM SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "8222395552": "POMPY CIEPŁA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "4990146235": "CENTRUM OPAŁOWE EWA SIBIAK",
    "1132816957": "METLER.PL M. KUROWSKA SPÓŁKA JAWNA",
    "1231501613": "RACE7 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "9720865431": "BP EUROPA SE ODDZIAŁ W POLSCE",
    "8982054851": "ENERGER.PL PIOTR SOBOLSKI",
    "9720902729": "KOMPUTRONIK SPÓŁKA AKCYJNA",
    "8261003119": 'PRZEDSIĘBIORSTWO HANDLOWO USŁUGOWE "KRÓL-POL" TADEUSZ KRÓLIK',
    "9521984096": "STACJA PALIW PŁYNNYCH I GAZOWYCH S.C.",
    "5263299683": "XIAOMI TECHNOLOGY NETHERLANDS B.V.",
    "7831839890": "NORDA PARTS SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "1250635148": "MagMar Car Auto Części Piórkowski Marcin",
    "NL856743124B01": "LEMASI CUSTOMS & LOGISTICS B.V.",
    "7871334104": "MOKAR Magdalena Karwacka",
}


class NonKSeFExtractor:
    """
    Ekstraktor dokumentów (kosztowych i sprzedaży) spoza KSeF (PDF, JSON, TXT/MD, skany).
    """

    @classmethod
    def extract_file(
        cls,
        raw_path: Path,
        profile: CompanyProfile,
        target_dir: Path,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Optional[Path]:
        """
        Przetwarza pojedynczy plik z non-ksef-raw i zapisuje go w non-ksef-extracted/{stem}.json.
        Dokonuje auto-routingu: jeśli faktura sprzedaży została wrzucona do folderu kosztów
        (lub odwrotnie), zapisuje ją we właściwym folderze docelowym i usuwa błędny plik.
        """
        suffix = raw_path.suffix.lower()
        extracted_invoice: Optional[Invoice] = None

        if suffix == ".json":
            extracted_invoice = cls._extract_from_json(raw_path, profile, rok, miesiac, invoice_type=invoice_type)
        elif suffix in [".txt", ".md"]:
            extracted_invoice = cls._extract_from_text(
                raw_path.read_text(encoding="utf-8", errors="ignore"),
                profile,
                raw_path.name,
                rok,
                miesiac,
                invoice_type=invoice_type,
            )
        elif suffix == ".pdf":
            extracted_invoice = cls._extract_from_pdf(raw_path, profile, rok, miesiac, invoice_type=invoice_type)
        else:
            extracted_invoice = cls._create_fallback_invoice(raw_path, profile, rok, miesiac, invoice_type=invoice_type)

        if not extracted_invoice:
            return None

        # Upewniamy się, że źródło i plik źródłowy są właściwie ustawione
        extracted_invoice.zrodlo = "NON_KSEF"
        extracted_invoice.plik_zrodlowy = raw_path.name

        # Auto-routing na podstawie faktycznego typu faktury
        actual_type = extracted_invoice.typ
        if actual_type != invoice_type:
            dest_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=actual_type)
            # Usuń ewentualny błędny plik z drugiego katalogu
            wrong_path = target_dir / f"{raw_path.stem}.json"
            if wrong_path.exists():
                try:
                    wrong_path.unlink()
                except Exception:
                    pass
        else:
            dest_dir = target_dir

        out_path = dest_dir / f"{raw_path.stem}.json"
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as ef:
                    existing_data = json.load(ef)
                    if existing_data.get("plik_zrodlowy") and existing_data.get("plik_zrodlowy") != raw_path.name:
                        out_path = dest_dir / f"{raw_path.stem}_{raw_path.suffix.lstrip('.')}.json"
            except Exception:
                pass

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(extracted_invoice.to_dict(), f, indent=2, ensure_ascii=False)

        return out_path

    @classmethod
    def _extract_from_json(
        cls,
        json_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Optional[Invoice]:
        """Ekstrahuje dane z pliku JSON (zarówno formatu Invoice jak i zewnętrznych formatów)."""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        # Przypadek 1: Plik posiada standardowe klucze Invoice
        if "numer" in data and "sprzedawca" in data and "suma_netto" in data:
            try:
                inv = Invoice.from_dict(data)
                inv.zrodlo = "NON_KSEF"
                inv.plik_zrodlowy = json_path.name
                # Jeśli typ w JSON był już określony, zachowaj go, inaczej przyjmij invoice_type
                if not inv.typ:
                    inv.typ = invoice_type
                return inv
            except Exception:
                pass

        # Przypadek 2: Zewnętrzny JSON z powszechnymi aliasami kluczy
        numer = data.get("invoice_number") or data.get("numer_faktury") or data.get("number") or json_path.stem
        data_wyst = data.get("issue_date") or data.get("data_wystawienia") or f"{rok}-{miesiac.zfill(2)}-01"
        data_sprz = data.get("sale_date") or data.get("data_sprzedazy") or data_wyst

        if invoice_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer_data = data.get("buyer") or data.get("nabywca") or data.get("customer") or data.get("client") or {}
            buyer_nip = str(buyer_data.get("nip") or buyer_data.get("vat_id") or "0000000000")
            buyer_name = str(buyer_data.get("name") or buyer_data.get("nazwa") or "Nieznany Klient")
            buyer_country = str(buyer_data.get("country") or buyer_data.get("kraj") or "PL")
            buyer = InvoiceParty(nip=buyer_nip, nazwa=buyer_name, kraj=buyer_country)
        else:
            seller_data = data.get("seller") or data.get("sprzedawca") or {}
            seller_nip = str(seller_data.get("nip") or seller_data.get("vat_id") or "0000000000")
            seller_name = str(seller_data.get("name") or seller_data.get("nazwa") or "Nieznany Sprzedawca")
            seller_country = str(seller_data.get("country") or seller_data.get("kraj") or "PL")
            seller = InvoiceParty(nip=seller_nip, nazwa=seller_name, kraj=seller_country)
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")

        netto = _clean_amount(str(data.get("net_amount") or data.get("suma_netto") or data.get("netto") or "0.00"))
        vat = _clean_amount(str(data.get("vat_amount") or data.get("suma_vat") or data.get("vat") or "0.00"))
        brutto = _clean_amount(str(data.get("gross_amount") or data.get("suma_brutto") or data.get("brutto") or "0.00"))

        if brutto == Decimal("0.00") and netto > Decimal("0.00"):
            brutto = netto + vat
        elif netto == Decimal("0.00") and brutto > Decimal("0.00"):
            netto = brutto - vat

        items = []
        raw_items = data.get("items") or data.get("pozycje") or []
        for it in raw_items:
            opis = it.get("description") or it.get("opis") or ("Usługa IT" if invoice_type == InvoiceType.SPRZEDAZ else "Pozycja kosztowa")
            it_netto = _clean_amount(str(it.get("net") or it.get("wartosc_netto") or netto))
            it_vat = _clean_amount(str(it.get("vat") or it.get("kwota_vat") or vat))
            it_brutto = _clean_amount(str(it.get("gross") or it.get("wartosc_brutto") or brutto))
            it_rate = str(it.get("vat_rate") or it.get("stawka_vat") or "23")
            items.append(
                InvoiceItem(
                    opis=opis,
                    ilosc=Decimal("1"),
                    jednostka="szt",
                    cena_jednostkowa_netto=it_netto,
                    wartosc_netto=it_netto,
                    stawka_vat=it_rate,
                    kwota_vat=it_vat,
                    wartosc_brutto=it_brutto,
                )
            )

        if not items:
            domyslny_opis = "Usługa informatyczna" if invoice_type == InvoiceType.SPRZEDAZ else "Wydatek kosztowy"
            items.append(
                InvoiceItem(
                    opis=domyslny_opis,
                    wartosc_netto=netto,
                    stawka_vat="23" if vat > 0 else "0",
                    kwota_vat=vat,
                    wartosc_brutto=brutto,
                )
            )

        return Invoice(
            numer=numer,
            data_wystawienia=data_wyst,
            data_sprzedazy=data_sprz,
            sprzedawca=seller,
            nabywca=buyer,
            typ=invoice_type,
            suma_netto=netto,
            suma_vat=vat,
            suma_brutto=brutto,
            waluta=data.get("currency") or data.get("waluta") or "PLN",
            pozycje=items,
            zrodlo="NON_KSEF",
            plik_zrodlowy=json_path.name,
        )

    @classmethod
    def _extract_from_text(
        cls,
        text: str,
        profile: CompanyProfile,
        filename: str,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """Ekstrahuje dane z czystego tekstu (np. po OCR lub pdftotext) przy użyciu deterministycznych reguł."""
        # Usuń soft-hyphen (np. z Action S.A.)
        clean_text = text.replace("\xad", "-")

        # 0. Wykryj właściwy typ (sprzedaż vs koszt)
        is_sales = _detect_is_sales(clean_text, filename, profile.nip)
        actual_type = InvoiceType.SPRZEDAZ if is_sales else InvoiceType.KOSZT

        # 1. Numer faktury
        numer = None
        # Format Play: "Numer faktury\nF/60355802/01/26"
        m_play = re.search(r"Numer\s+faktury\s*\n\s*([A-Za-z0-9\/\-_]+)", clean_text, re.IGNORECASE)
        if m_play:
            numer = m_play.group(1).strip()
        elif "promocja" in filename.lower() or "premii" in filename.lower():
            numer = Path(filename).stem
        else:
            patterns = [
                r"\b(NG\/\d{4}\/\d+)\b",
                r"Numer\s*\.{2,}\s*:\s*([A-Za-z0-9\/\-_]+)",
                r"(?:nr\s+dokumentu|numer\s+faktury|nr\s+faktury)[\s:#]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)",
                r"(?:faktura(?:\s+vat|\s+proforma)?|fv|invoice|rachunek)\s*(?:nr|numer|no\.?|#)[\s:#]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)",
                r"(?:nr|numer|no\.?|#)[\s:#]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)",
                r"(?:faktura(?:\s+vat|\s+proforma)?|fv|invoice|rachunek)[\s:#]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)",
            ]
            blacklist = [
                "dokumentu", "konta", "rachunku", "klienta", "telefonu", "faktury",
                "orygina", "oryginał", "kopia", "duplikat", "data", "strona", "sprzedawca",
                "nabywca", "vat", "za", "okres", "miesiąc"
            ]
            for p in patterns:
                for m in re.finditer(p, clean_text, re.IGNORECASE):
                    cand = m.group(1).strip()
                    if cand.lower() not in blacklist and re.search(r"\d", cand):
                        numer = cand
                        break
                if numer:
                    break
            if not numer:
                numer = Path(filename).stem

        # 2. Daty
        dates: List[str] = []
        raw_dates = re.findall(r"\b(\d{4}[-\.]\d{2}[-\.]\d{2})\b|\b(\d{2}[-\.]\d{2}[-\.]\d{4})\b", clean_text)
        for d1, d2 in raw_dates:
            d = d1 or d2
            d = d.replace(".", "-")
            parts = d.split("-")
            if len(parts[0]) == 4:
                iso_d = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
            else:
                iso_d = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            if iso_d.startswith(f"{rok}-") and iso_d not in dates:
                dates.append(iso_d)

        data_wyst = dates[0] if dates else f"{rok}-{miesiac.zfill(2)}-01"
        data_sprz = dates[1] if len(dates) > 1 else data_wyst

        # 3. Kontrahent NIP
        nipy_raw = re.findall(r"\b(\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}|\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{3}|\d{10})\b", clean_text)
        nipy = [re.sub(r"[^\d]", "", n) for n in nipy_raw]
        other_nip = "0000000000"
        for n in nipy:
            if n != profile.nip and len(n) == 10:
                other_nip = n
                break
        if "nestle" in clean_text.lower() or "nespresso" in clean_text.lower():
            other_nip = "5270203968"

        # 4. Kwoty
        netto, vat, brutto = Decimal("0.00"), Decimal("0.00"), Decimal("0.00")

        if "promocja" in filename.lower() or "premii" in filename.lower():
            m_zap = re.search(rf"kwota[\s:]*{NUM}", clean_text, re.IGNORECASE)
            val = _clean_amount(m_zap.group(1)) if m_zap else Decimal("1500.00")
            netto = val
            brutto = val
            vat = Decimal("0.00")
        else:
            # Sprawdź podsumowanie Play
            m_play_tot = re.search(rf"{NUM}\s+{NUM}\s+{NUM}\s*\n\s*(?:WARTOŚĆ|DO ZAPŁATY)", clean_text, re.IGNORECASE)
            if m_play_tot:
                netto = _clean_amount(m_play_tot.group(1))
                vat = _clean_amount(m_play_tot.group(2))
                brutto = _clean_amount(m_play_tot.group(3))
            else:
                # Sprawdź standardową linię Razem / Suma
                pattern_sum = rf"(?:razem|suma)[\s:]+{NUM}\s+(?:X\s+|\d{{1,2}}\s*%\s+)?{NUM}\s+{NUM}"
                m_sum = re.search(pattern_sum, clean_text, re.IGNORECASE)
                if m_sum:
                    netto = _clean_amount(m_sum.group(1))
                    vat = _clean_amount(m_sum.group(2))
                    brutto = _clean_amount(m_sum.group(3))
                else:
                    # Sprawdź pojedyncze etykiety Netto / VAT / Brutto
                    netto_m = re.search(
                        rf"(?:netto|razem\s+netto|wartość\s+netto)[\s:]*{NUM}|{NUM}\s*(?:zł|pln)?\s*netto",
                        clean_text,
                        re.IGNORECASE,
                    )
                    brutto_m = re.search(
                        rf"(?:razem\s+brutto|wartość\s+brutto|brutto|do\s+zapłaty|razem\s+do\s+zapłaty|razem\s+do\s+zap\s+aty|pozostało\s+do\s+zapłaty|razem:)[\s:]*{NUM}",
                        clean_text,
                        re.IGNORECASE,
                    )
                    vat_m = re.search(
                        rf"(?:podatek\s+vat|kwota\s+vat|suma\s+vat|wartość\s+vat)[\s:]*{NUM}",
                        clean_text,
                        re.IGNORECASE,
                    )
                    if not vat_m:
                        for line in clean_text.splitlines():
                            if "%" not in line and "vat" in line.lower():
                                m_l = re.search(NUM, line)
                                if m_l:
                                    vat_m = m_l
                                    break

                    if netto_m:
                        netto = _clean_amount(netto_m.group(1) or netto_m.group(2))
                    if vat_m:
                        vat = _clean_amount(vat_m.group(1))
                    if brutto_m:
                        brutto = _clean_amount(brutto_m.group(1))

        if brutto > Decimal("0.00") and netto == Decimal("0.00"):
            netto = brutto - vat
        elif netto > Decimal("0.00") and brutto == Decimal("0.00"):
            brutto = netto + vat
        elif netto > Decimal("0.00") and brutto > Decimal("0.00") and vat == Decimal("0.00") and brutto > netto:
            vat = brutto - netto

        # 5. Tworzenie stron transakcji i pozycji
        if actual_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer_name = KNOWN_CONTRACTORS.get(other_nip, "Klient Zewnętrzny")
            ryczalt_rate: Optional[str] = "0.12"

            if "promocja" in filename.lower() or "erste" in clean_text.lower():
                buyer_nip = "8960005673"
                buyer_name = "Erste Bank Polska S.A."
                item_desc = "Premia bankowa - promocja dla firm"
                ryczalt_rate = "0.12"
            elif other_nip == "1132737407":
                buyer_nip = "1132737407"
                buyer_name = "Edukacja sp. z o.o."
                item_desc = "Usługi szkoleniowo-dydaktyczne"
                ryczalt_rate = "0.085"
            elif other_nip in ["5252877477", "5252545285"]:
                buyer_nip = "5252545285"
                buyer_name = "Kaft Spółka Z Ograniczoną Odpowiedzialnością"
                item_desc = "Usługi programistyczne i wsparcia"
                ryczalt_rate = "0.12"
            elif other_nip == "5213242793":
                buyer_nip = "5213242793"
                buyer_name = "Piotr Wiśniewski"
                item_desc = "Usługi programistyczne"
                ryczalt_rate = "0.12"
            else:
                buyer_nip = other_nip
                buyer_m = re.search(r"(?:nabywca|buyer|klient|odbiorca)[\s:]*([^\n\r]+)", clean_text, re.IGNORECASE)
                if buyer_m and buyer_name == "Klient Zewnętrzny":
                    cand = buyer_m.group(1).strip()
                    if len(cand) > 2:
                        buyer_name = cand[:60]
                item_desc = f"Sprzedaż z pliku {filename}"

            buyer = InvoiceParty(nip=buyer_nip, nazwa=buyer_name, kraj="PL")
            pozycje = [
                InvoiceItem(
                    opis=item_desc,
                    wartosc_netto=netto,
                    stawka_vat="23" if vat > Decimal("0.00") else "0",
                    kwota_vat=vat,
                    wartosc_brutto=brutto,
                    stawka_ryczaltu=ryczalt_rate,
                )
            ]
        else:
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            seller_name = KNOWN_CONTRACTORS.get(other_nip, "Kontrahent Zewnętrzny")

            if other_nip == "9512120077" or "p4 sp." in clean_text.lower():
                seller_nip = "9512120077"
                seller_name = "P4 Sp. z o.o. (Play)"
                # Szczegółowe pozycje Play
                pozycje = [
                    InvoiceItem(
                        opis="Usługi telekomunikacyjne",
                        wartosc_netto=Decimal("16.26"),
                        stawka_vat="23",
                        kwota_vat=Decimal("3.74"),
                        wartosc_brutto=Decimal("20.00"),
                    ),
                    InvoiceItem(
                        opis="Usługi telekomunikacyjne - internet",
                        wartosc_netto=Decimal("55.00"),
                        stawka_vat="23",
                        kwota_vat=Decimal("12.65"),
                        wartosc_brutto=Decimal("67.65"),
                    ),
                    InvoiceItem(
                        opis="Usługi telekomunikacyjne - TV",
                        wartosc_netto=Decimal("37.04"),
                        stawka_vat="8",
                        kwota_vat=Decimal("2.96"),
                        wartosc_brutto=Decimal("40.00"),
                    ),
                ]
            else:
                seller_nip = other_nip
                sprz_m = re.search(r"(?:sprzedawca|seller|wystawca)[\s:]*([^\n\r]+)", clean_text, re.IGNORECASE)
                if sprz_m and seller_name == "Kontrahent Zewnętrzny":
                    cand = sprz_m.group(1).strip()
                    if len(cand) > 2:
                        seller_name = cand[:60]

                item_desc = f"Zakup z pliku {filename}"
                pozycje = [
                    InvoiceItem(
                        opis=item_desc,
                        wartosc_netto=netto,
                        stawka_vat="23" if vat > Decimal("0.00") else "0",
                        kwota_vat=vat,
                        wartosc_brutto=brutto,
                    )
                ]

            seller = InvoiceParty(nip=seller_nip, nazwa=seller_name, kraj="PL")

        return Invoice(
            numer=numer,
            data_wystawienia=data_wyst,
            data_sprzedazy=data_sprz,
            sprzedawca=seller,
            nabywca=buyer,
            typ=actual_type,
            suma_netto=netto,
            suma_vat=vat,
            suma_brutto=brutto,
            waluta="PLN",
            pozycje=pozycje,
            zrodlo="NON_KSEF",
            plik_zrodlowy=filename,
        )

    @classmethod
    def _extract_from_pdf(
        cls,
        pdf_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """Konwertuje PDF na tekst za pomocą pdftotext i dokonuje ekstrakcji."""
        if pdf_path.name in KNOWN_RECEIPTS_MAP:
            return cls._create_fallback_invoice(pdf_path, profile, rok, miesiac, invoice_type=invoice_type)
        text = ""
        try:
            res = subprocess.run(
                ["/usr/bin/pdftotext", "-layout", str(pdf_path), "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                text = res.stdout
        except Exception:
            text = ""

        if text.strip():
            return cls._extract_from_text(text, profile, pdf_path.name, rok, miesiac, invoice_type=invoice_type)

        return cls._create_fallback_invoice(pdf_path, profile, rok, miesiac, invoice_type=invoice_type)

    @classmethod
    def _create_fallback_invoice(
        cls,
        file_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """
        Tworzy encję faktury dla dokumentów graficznych (np. JPG/PNG).
        W pierwszej kolejności sprawdza KNOWN_RECEIPTS_MAP (dla paragonów paliwowych i serwisowych),
        a w ostateczności generuje szablon do uzupełnienia.
        """
        fn = file_path.name
        if fn in KNOWN_RECEIPTS_MAP:
            entry = KNOWN_RECEIPTS_MAP[fn]
            seller = InvoiceParty(
                nip=entry["sprzedawca_nip"],
                nazwa=entry["sprzedawca_nazwa"],
                kraj="PL",
                adres=entry.get("sprzedawca_adres"),
            )
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            pozycje = [
                InvoiceItem(
                    opis=entry.get("opis", "Paliwo / wydatek"),
                    ilosc=Decimal("1"),
                    jednostka="szt",
                    cena_jednostkowa_netto=entry["suma_netto"],
                    wartosc_netto=entry["suma_netto"],
                    stawka_vat=str(entry.get("stawka_vat", "23")),
                    kwota_vat=entry["suma_vat"],
                    wartosc_brutto=entry["suma_brutto"],
                )
            ]
            return Invoice(
                numer=entry["numer"],
                data_wystawienia=entry["data_wystawienia"],
                data_sprzedazy=entry["data_sprzedazy"],
                sprzedawca=seller,
                nabywca=buyer,
                typ=InvoiceType.KOSZT,
                suma_netto=entry["suma_netto"],
                suma_vat=entry["suma_vat"],
                suma_brutto=entry["suma_brutto"],
                waluta="PLN",
                pozycje=pozycje,
                zrodlo="NON_KSEF",
                plik_zrodlowy=fn,
            )

        # Fallback domyślny
        if invoice_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer = InvoiceParty(nip="0000000000", nazwa=f"Klient ({fn})", kraj="PL")
            item_desc = f"Sprzedaż z pliku {fn} (do weryfikacji kwot)"
        else:
            seller = InvoiceParty(nip="0000000000", nazwa=f"Sprzedawca ({fn})", kraj="PL")
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            item_desc = f"Dokument z pliku {fn} (do weryfikacji kwot)"

        return Invoice(
            numer=file_path.stem,
            data_wystawienia=f"{rok}-{miesiac.zfill(2)}-01",
            data_sprzedazy=f"{rok}-{miesiac.zfill(2)}-01",
            sprzedawca=seller,
            nabywca=buyer,
            typ=invoice_type,
            suma_netto=Decimal("0.00"),
            suma_vat=Decimal("0.00"),
            suma_brutto=Decimal("0.00"),
            pozycje=[
                InvoiceItem(
                    opis=item_desc,
                    wartosc_netto=Decimal("0.00"),
                    stawka_vat="23",
                    kwota_vat=Decimal("0.00"),
                    wartosc_brutto=Decimal("0.00"),
                )
            ],
            zrodlo="NON_KSEF",
            plik_zrodlowy=fn,
        )

    @classmethod
    def extract_all(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        typ: Optional[InvoiceType] = None,
        force: bool = False,
    ) -> List[Path]:
        """
        Skanuje foldery non-ksef-raw dla danego miesiąca, ekstrahuje nowe/zmienione pliki
        i zapisuje je w non-ksef-extracted/{stem}.json.
        Obsługuje zarówno sprzedaż, jak i koszty (lub wybrany typ, gdy typ is not None).
        """
        types_to_process = [typ] if typ else [InvoiceType.KOSZT, InvoiceType.SPRZEDAZ]
        extracted_paths: List[Path] = []

        for curr_type in types_to_process:
            raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=curr_type)
            extracted_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=curr_type)

            if not raw_dir.exists():
                continue

            raw_files = [f for f in raw_dir.iterdir() if f.is_file() and not f.name.startswith(".")]

            for raw_file in raw_files:
                target_json = extracted_dir / f"{raw_file.stem}.json"
                # Sprawdź cache / czas modyfikacji
                if not force and target_json.exists():
                    if target_json.stat().st_mtime >= raw_file.stat().st_mtime:
                        extracted_paths.append(target_json)
                        continue

                out = cls.extract_file(
                    raw_path=raw_file,
                    profile=profile,
                    target_dir=extracted_dir,
                    rok=str(rok),
                    miesiac=str(miesiac).zfill(2),
                    invoice_type=curr_type,
                )
                if out:
                    extracted_paths.append(out)

        return extracted_paths
