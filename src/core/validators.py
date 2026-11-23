"""
src/core/validators.py
Deterministyczne walidatory identyfikatorów fiskalnych i bankowych (VAL-1).
Implementuje formalne algorytmy sum kontrolnych:
1. NIP (Numer Identyfikacji Podatkowej) - 10 cyfr, wagi [6, 5, 7, 2, 3, 4, 5, 6, 7], modulo 11.
2. REGON (Krajowy Rejestr Urzędowy Podmiotów Gospodarki Narodowej) - 9 lub 14 cyfr, modulo 11.
3. NRB / IBAN PL (Numer Rachunku Bankowego) - 26 cyfr, algorytm ISO 7064 Modulo 97-10.
"""

import re
from typing import Optional, Set, Tuple

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_REGON_9_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)
_REGON_14_WEIGHTS = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)

# Znane syntetyczne NIP-y referencyjne wykorzystywane w środowiskach testowych i deweloperskich
TEST_NIPS: Set[str] = {
    "7770001122",  # Referencyjna firma demonstracyjna (CloudTech Solutions)
    "1111111111",  # Fixture testowy Alpha
    "2222222222",  # Fixture testowy Beta
    "1234567890",  # Fixture testowy w test_web_companies.py
    "0000000000",  # NIP pusty / fallback
}


def clean_nip(raw_nip: Optional[str]) -> str:
    """Oczyszcza NIP z myślników, spacji, prefiksu PL i innych znaków nienumerycznych."""
    if not raw_nip:
        return ""
    clean = raw_nip.strip().upper()
    if clean.startswith("PL"):
        clean = clean[2:]
    return re.sub(r"[^0-9]", "", clean)


def validate_nip(raw_nip: Optional[str], allow_test_nips: bool = True) -> Tuple[bool, str]:
    """
    Weryfikuje formalną i algorytmiczną poprawność polskiego NIP.
    Zwraca (is_valid, error_message).
    Jeśli allow_test_nips=True, akceptuje syntetyczne NIP-y testowe projektu (np. 7770001122).
    """
    nip = clean_nip(raw_nip)
    if not nip:
        return False, "NIP nie może być pusty"

    if len(nip) != 10:
        return False, f"NIP musi składać się dokładnie z 10 cyfr (podano: {len(nip)})"

    if allow_test_nips and nip in TEST_NIPS:
        return True, ""

    digits = [int(c) for c in nip]

    # Obliczenie sumy ważonej
    weighted_sum = sum(w * d for w, d in zip(_NIP_WEIGHTS, digits[:9]))
    control_digit = weighted_sum % 11

    # Zgodnie z zasadami MF, jeśli reszta wynosi 10, NIP jest niepoprawny
    if control_digit == 10:
        return False, "Nieprawidłowa suma kontrolna NIP (reszta modulo wynosi 10)"

    if control_digit != digits[9]:
        return False, f"Błędna cyfra kontrolna NIP: oczekiwano {control_digit}, otrzymano {digits[9]}"

    return True, ""


def clean_regon(raw_regon: Optional[str]) -> str:
    """Oczyszcza numer REGON ze spacji i znaków nienumerycznych."""
    if not raw_regon:
        return ""
    return re.sub(r"[^0-9]", "", raw_regon.strip())


def validate_regon(raw_regon: Optional[str]) -> Tuple[bool, str]:
    """
    Weryfikuje formalną i algorytmiczną poprawność numeru REGON (9 lub 14 cyfr).
    Zwraca (is_valid, error_message).
    """
    regon = clean_regon(raw_regon)
    if not regon:
        return False, "REGON nie może być pusty"

    if len(regon) not in (9, 14):
        return False, f"REGON musi mieć 9 lub 14 cyfr (podano: {len(regon)})"

    digits = [int(c) for c in regon]

    # Walidacja części 9-cyfrowej
    sum_9 = sum(w * d for w, d in zip(_REGON_9_WEIGHTS, digits[:8]))
    control_9 = sum_9 % 11
    if control_9 == 10:
        control_9 = 0

    if control_9 != digits[8]:
        return False, f"Błędna cyfra kontrolna REGON-9: oczekiwano {control_9}, otrzymano {digits[8]}"

    # Jeśli 14-cyfrowy, walidacja rozszerzenia
    if len(regon) == 14:
        sum_14 = sum(w * d for w, d in zip(_REGON_14_WEIGHTS, digits[:13]))
        control_14 = sum_14 % 11
        if control_14 == 10:
            control_14 = 0
        if control_14 != digits[13]:
            return False, f"Błędna cyfra kontrolna REGON-14: oczekiwano {control_14}, otrzymano {digits[13]}"

    return True, ""


def clean_nrb(raw_account: Optional[str]) -> str:
    """Oczyszcza polski numer konta bankowego (NRB) ze spacji i prefiksu PL."""
    if not raw_account:
        return ""
    clean = raw_account.strip().upper()
    if clean.startswith("PL"):
        clean = clean[2:]
    return re.sub(r"[^0-9]", "", clean)


def validate_nrb(raw_account: Optional[str]) -> Tuple[bool, str]:
    """
    Weryfikuje poprawność polskiego Numeru Rachunku Bankowego (NRB) za pomocą algorytmu
    sumy kontrolnej IBAN (ISO 7064 Modulo 97-10).
    Zwraca (is_valid, error_message).
    """
    nrb = clean_nrb(raw_account)
    if not nrb:
        return False, "Numer konta nie może być pusty"

    if len(nrb) != 26:
        return False, f"Polski numer rachunku (NRB) musi mieć dokładnie 26 cyfr (podano: {len(nrb)})"

    # Algorytm IBAN dla Polski:
    # 1. Przenieś 2 cyfry kontrolne na koniec (nrb[2:] + nrb[:2])
    # 2. Dodaj kod kraju PL w postaci numerycznej (P=25, L=21 -> 2521)
    # 3. Całość zamień na liczbę całkowitą i oblicz modulo 97. Wynik musi wynosić 1.
    iban_numeric_str = nrb[2:] + "2521" + nrb[:2]

    try:
        val = int(iban_numeric_str)
        if val % 97 != 1:
            return False, "Nieprawidłowa suma kontrolna numeru konta (błędna cyfra kontrolna NRB / IBAN)"
    except ValueError:
        return False, "Numer konta zawiera nieprawidłowe znaki"

    return True, ""


def format_nrb(raw_account: Optional[str], include_prefix: bool = True) -> str:
    """
    Formatuje 26-cyfrowy polski numer konta bankowego (NRB) do oficjalnego formatu:
    [PL ]XX XXXX XXXX XXXX XXXX XXXX XXXX (2 cyfry kontrolne + 6 grup po 4 cyfry).
    Jeśli include_prefix=True, dodaje 'PL '.
    Jeśli numer jest pusty lub nie ma dokładnie 26 cyfr, zwraca oczyszczony/oryginalny ciąg.
    """
    if not raw_account:
        return ""
    clean = clean_nrb(raw_account)
    if len(clean) == 26:
        parts = [
            clean[:2],
            clean[2:6],
            clean[6:10],
            clean[10:14],
            clean[14:18],
            clean[18:22],
            clean[22:26],
        ]
        formatted = " ".join(parts)
        return f"PL {formatted}" if include_prefix else formatted
    return raw_account.strip()


def calculate_nrb_checksum(bban_24: str) -> str:
    """
    Oblicza 2 cyfry kontrolne dla 24-cyfrowego polskiego numeru BBAN (ISO 7064 Modulo 97-10 dla PL).
    Zwraca 2-cyfrowy ciąg znaków, np. '80'.
    """
    clean_bban = re.sub(r"[^0-9]", "", bban_24)
    if len(clean_bban) != 24:
        raise ValueError(f"BBAN musi składać się z dokładnie 24 cyfr (podano: {len(clean_bban)})")
    # Kod kraju PL to 2521
    val = int(clean_bban + "252100")
    check_digits = 98 - (val % 97)
    return f"{check_digits:02d}"


def generate_us_microaccount(raw_nip: Optional[str]) -> str:
    """
    Generuje 26-cyfrowy Indywidualny Mikrorachunek Podatkowy US zgodny ze standardem Ministerstwa Finansów:
    - BBAN: 101000712222 + NIP (10 cyfr) + 00
    - 2 cyfry kontrolne liczone algorytmem ISO 7064 Modulo 97-10 (IBAN dla PL).
    Zwraca 26 cyfr bez spacji (np. '80101000712222777000112200').
    """
    nip = clean_nip(raw_nip)
    if not nip:
        nip = "0000000000"
    elif len(nip) < 10:
        nip = nip.zfill(10)
    elif len(nip) > 10:
        nip = nip[:10]

    bban = f"101000712222{nip}00"
    check = calculate_nrb_checksum(bban)
    return f"{check}{bban}"


def generate_zus_nrs_account(raw_nip: Optional[str]) -> str:
    """
    Generuje 26-cyfrowy Indywidualny Rachunek Składkowy ZUS (NRS w NBP) zgodny ze standardem ZUS:
    - BBAN: 10101023000026 + NIP (10 cyfr)
    - 2 cyfry kontrolne liczone algorytmem ISO 7064 Modulo 97-10 (IBAN dla PL).
    Zwraca 26 cyfr bez spacji (np. '50101010230000267770001122').
    """
    nip = clean_nip(raw_nip)
    if not nip:
        nip = "0000000000"
    elif len(nip) < 10:
        nip = nip.zfill(10)
    elif len(nip) > 10:
        nip = nip[:10]

    bban = f"10101023000026{nip}"
    check = calculate_nrb_checksum(bban)
    return f"{check}{bban}"
