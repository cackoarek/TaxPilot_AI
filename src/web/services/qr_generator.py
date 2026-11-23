"""
src/web/services/qr_generator.py
Deterministyczny generator kodów QR dla polskich przelewów bankowych (Standard ZBP / Elixir).
Umożliwia błyskawiczne opłacenie podatków i ZUS aplikacją bankową na smartfonie.
"""

import base64
import io
import re
from decimal import Decimal
from typing import Any, Dict, Union

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from src.core.validators import format_nrb


def clean_account_number(account: str) -> str:
    """Usuwa spacje i myślniki z numeru rachunku bankowego."""
    if not account:
        return ""
    clean = re.sub(r"[^0-9]", "", str(account))
    return clean


def format_zbp_payload(
    rachunek: str,
    kwota: Union[Decimal, float, str, int],
    nazwa_odbiorcy: str,
    tytul_przelewu: str,
) -> str:
    """
    Formatuje ciąg danych zgodnie z Rekomendacją ZBP (Związek Banków Polskich)
    dla kodów 2D/QR płatności mobilnych:
    ||{rachunek_26_cyfr}|{kwota_w_groszach_min_6_cyfr}|{nazwa_odbiorcy}|{tytul_przelewu}|||
    """
    clean_acc = clean_account_number(rachunek)

    # Przeliczenie kwoty na grosze
    if not isinstance(kwota, Decimal):
        kwota_dec = Decimal(str(kwota).replace(" ", "").replace(",", "."))
    else:
        kwota_dec = kwota

    kwota_grosze = int((kwota_dec * Decimal("100")).quantize(Decimal("1")))
    # Format kwoty w groszach - minimum 6 cyfr z wiodącymi zerami (np. 15000 -> 015000)
    kwota_str = f"{kwota_grosze:06d}"

    nazwa_clean = (nazwa_odbiorcy or "").strip()[:70]
    tytul_clean = (tytul_przelewu or "").strip()[:140]

    # Standard ZBP format
    return f"||{clean_acc}|{kwota_str}|{nazwa_clean}|{tytul_clean}|||"


def generate_qr_base64_data_uri(
    payload: str,
    box_size: int = 6,
    border: int = 2,
) -> str:
    """Generuje obraz kodu QR jako Data URI w formacie image/png."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


def get_transfer_qr_package(
    typ: str,
    rachunek: str,
    kwota: Union[Decimal, float, str],
    rok: str,
    miesiac: str,
    nip: str,
    nazwa_firmy: str = "",
) -> Dict[str, Any]:
    """
    Przygotowuje kompletną paczkę przelewu z kodem QR:
    - typ: 'PIT-28' | 'VAT-7' | 'ZUS'
    """
    clean_acc = clean_account_number(rachunek)
    okres = f"{rok}-{miesiac}"

    if typ.upper() == "PIT-28":
        odbiorca = "Urząd Skarbowy (Mikrorachunek Podatkowy)"
        tytul = f"PIT-28 za {okres} NIP {nip}"
    elif typ.upper() == "VAT-7":
        odbiorca = "Urząd Skarbowy (Mikrorachunek Podatkowy)"
        tytul = f"VAT-7 za {okres} NIP {nip}"
    elif typ.upper() == "ZUS":
        odbiorca = "ZUS (Indywidualny Rachunek Składkowy NRS)"
        tytul = f"Składki ZUS za {okres} NIP {nip}"
    else:
        odbiorca = "Odbiorca"
        tytul = f"Przelew {typ} za {okres}"

    payload = format_zbp_payload(
        rachunek=clean_acc,
        kwota=kwota,
        nazwa_odbiorcy=odbiorca,
        tytul_przelewu=tytul,
    )
    qr_uri = generate_qr_base64_data_uri(payload)

    return {
        "typ": typ,
        "odbiorca": odbiorca,
        "rachunek": clean_acc,
        "rachunek_sformatowany": format_nrb(clean_acc, include_prefix=True),
        "kwota": kwota,
        "tytul": tytul,
        "payload": payload,
        "qr_data_uri": qr_uri,
    }
