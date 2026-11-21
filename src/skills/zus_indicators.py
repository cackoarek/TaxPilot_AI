"""
Moduł zarządzania wskaźnikami makroekonomicznymi ZUS i GUS.
Zapewnia trzystopniowy mechanizm:
1. Oficjalne obwieszczenia Prezesa GUS i MRPiPS (lokalna baza wiedzy).
2. Próba pobrania aktualnych wskaźników online (jeśli dostępne połączenie sieciowe).
3. Bezpieczny fallback (szacunek prognozowany z ostrzeżeniem dla użytkownika).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "wskazniki_zus_cache.json"


@dataclass
class ZUSMacroParams:
    rok: str
    podstawa_pelny_zus: Decimal
    podstawa_preferencyjny_zus: Decimal
    przecietne_wynagrodzenie_zdrowotna: Decimal
    zrodlo: str  # "OFICJALNE_GUS", "POBRANE_ONLINE", "PROGNOZA_SZACOWANA", "PROFIL_UZYTKOWNIKA"
    ostrzezenie: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rok": self.rok,
            "podstawa_pelny_zus": str(self.podstawa_pelny_zus),
            "podstawa_preferencyjny_zus": str(self.podstawa_preferencyjny_zus),
            "przecietne_wynagrodzenie_zdrowotna": str(self.przecietne_wynagrodzenie_zdrowotna),
            "zrodlo": self.zrodlo,
            "ostrzezenie": self.ostrzezenie,
        }


# Oficjalne wskaźniki zatwierdzone przez Prezesa GUS / MRPiPS w Monitorze Polskim:
# - 2026:
#   * prognozowane przeciętne wynagrodzenie miesięczne: 9 420.00 zł
#   * podstawa pełny ZUS (60% prognozowanego przeciętnego wynagrodzenia): 5 652.00 zł
#   * płaca minimalna: 4 806.00 zł
#   * podstawa preferencyjny ZUS (30% płacy minimalnej): 1 441.80 zł
#   * przeciętne wynagrodzenie w IV kw. do składki zdrowotnej: 9 228.64 zł
#     (co przy 9% daje składkę: 830.58 zł dla II progu 60k-300k zł, 498.35 zł dla I progu, 1495.04 zł dla III progu)
# - 2025:
#   * prognozowane przeciętne wynagrodzenie miesięczne: 8 673.00 zł
#   * podstawa pełny ZUS (60% prognozowanego przeciętnego wynagrodzenia): 5 203.80 zł
#   * płaca minimalna: 4 666.00 zł
#   * podstawa preferencyjny ZUS (30% płacy minimalnej): 1 399.80 zł
#   * przeciętne wynagrodzenie w IV kw. do zdrowotnej: 8 549.18 zł
OFICJALNE_WSKAZNIKI: Dict[str, ZUSMacroParams] = {
    "2026": ZUSMacroParams(
        rok="2026",
        podstawa_pelny_zus=Decimal("5652.00"),
        podstawa_preferencyjny_zus=Decimal("1441.80"),
        przecietne_wynagrodzenie_zdrowotna=Decimal("9228.64"),
        zrodlo="OFICJALNE_GUS",
        ostrzezenie=None,
    ),
    "2025": ZUSMacroParams(
        rok="2025",
        podstawa_pelny_zus=Decimal("5203.80"),
        podstawa_preferencyjny_zus=Decimal("1399.80"),
        przecietne_wynagrodzenie_zdrowotna=Decimal("8549.18"),
        zrodlo="OFICJALNE_GUS",
        ostrzezenie=None,
    ),
}


def fetch_online_indicators(rok: str, timeout: float = 2.0) -> Optional[ZUSMacroParams]:
    """
    Podejmuje próbę pobrania najnowszych wskaźników makroekonomicznych ZUS/GUS online.
    Jeśli sieć jest niedostępna (np. tryb sandbox) lub brak endpointu, zwraca None bez rzucania wyjątków.
    """
    try:
        import urllib.request
        # Publiczne repozytorium wskaźników lub endpoint BDL GUS
        url = f"https://api.stat.gov.pl/indicators/zus/{rok}"
        req = urllib.request.Request(url, headers={"User-Agent": "TaxPilot-AI/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return ZUSMacroParams(
                    rok=str(rok),
                    podstawa_pelny_zus=Decimal(str(data["podstawa_pelny_zus"])),
                    podstawa_preferencyjny_zus=Decimal(str(data["podstawa_preferencyjny_zus"])),
                    przecietne_wynagrodzenie_zdrowotna=Decimal(str(data["przecietne_wynagrodzenie_zdrowotna"])),
                    zrodlo="POBRANE_ONLINE",
                    ostrzezenie=None,
                )
    except Exception as e:
        logger.debug(f"Pobieranie wskaźników online dla roku {rok} nie powiodło się: {e}")
    return None


def load_from_cache(rok: str, cache_path: Optional[Path] = None) -> Optional[ZUSMacroParams]:
    """Wczytuje wskaźniki dla danego roku z trwałego lokalnego pliku cache (JSON)."""
    path = cache_path or DEFAULT_CACHE_FILE
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rok_str = str(rok)
        if rok_str in data:
            entry = data[rok_str]
            return ZUSMacroParams(
                rok=rok_str,
                podstawa_pelny_zus=Decimal(str(entry["podstawa_pelny_zus"])),
                podstawa_preferencyjny_zus=Decimal(str(entry["podstawa_preferencyjny_zus"])),
                przecietne_wynagrodzenie_zdrowotna=Decimal(str(entry["przecietne_wynagrodzenie_zdrowotna"])),
                zrodlo=entry.get("zrodlo", "CACHE_DYSKOWY"),
                ostrzezenie=entry.get("ostrzezenie"),
            )
    except Exception as e:
        logger.debug(f"Błąd odczytu wskaźników z cache {path}: {e}")
    return None


def save_to_cache(params: ZUSMacroParams, cache_path: Optional[Path] = None) -> None:
    """Zapisuje wskaźniki na stałe do lokalnego pliku cache na dysku."""
    path = cache_path or DEFAULT_CACHE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = {}
        data[params.rok] = params.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Nie udało się zapisać wskaźników do cache {path}: {e}")


def is_official(params: ZUSMacroParams) -> bool:
    """
    Zwraca True jeśli wskaźniki pochodzą z oficjalnej bazy GUS lub zostały
    wprowadzone / zweryfikowane przez użytkownika.
    Zwraca False, jeśli są to automatyczne szacunki algorytmiczne (PROGNOZA_SZACOWANA).
    """
    if params.zrodlo in ("OFICJALNE_GUS", "ZWERYFIKOWANE", "WPROWADZONE_RECZNIE", "PROFIL_UZYTKOWNIKA") and not params.ostrzezenie:
        return True
    return False


def update_zus_indicators(
    rok: str,
    podstawa_pelny_zus: Decimal,
    podstawa_preferencyjny_zus: Decimal,
    przecietne_wynagrodzenie_zdrowotna: Decimal,
    zrodlo: str = "WPROWADZONE_RECZNIE",
    cache_path: Optional[Path] = None,
) -> ZUSMacroParams:
    """
    Zapisuje lub aktualizuje wskaźniki makroekonomiczne ZUS/GUS dla danego roku w trwałym pliku cache.
    """
    params = ZUSMacroParams(
        rok=str(rok),
        podstawa_pelny_zus=podstawa_pelny_zus,
        podstawa_preferencyjny_zus=podstawa_preferencyjny_zus,
        przecietne_wynagrodzenie_zdrowotna=przecietne_wynagrodzenie_zdrowotna,
        zrodlo=zrodlo,
        ostrzezenie=None,
    )
    save_to_cache(params, cache_path=cache_path)
    return params


def calculate_zus_breakdown_preview(params: ZUSMacroParams) -> Dict[str, Any]:
    """
    Przygotowuje zestawienie podglądowe stawek i wyliczeń składek społecznych oraz zdrowotnej
    w oparciu o podane wskaźniki makroekonomiczne na dany rok.
    Używane w interfejsie webowym w zakładce 'Księgowanie'.
    """
    stopa_emerytalna = Decimal("0.1952")
    stopa_rentowa = Decimal("0.0800")
    stopa_chorobowa = Decimal("0.0245")
    stopa_wypadkowa = Decimal("0.0167")
    stopa_fp = Decimal("0.0245")
    stopa_zdrowotna = Decimal("0.0900")

    def _rnd(val: Decimal) -> Decimal:
        return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Pełny ZUS
    p_pelny = params.podstawa_pelny_zus
    pelny_emerytalna = _rnd(p_pelny * stopa_emerytalna)
    pelny_rentowa = _rnd(p_pelny * stopa_rentowa)
    pelny_chorobowa = _rnd(p_pelny * stopa_chorobowa)
    pelny_wypadkowa = _rnd(p_pelny * stopa_wypadkowa)
    pelny_fp = _rnd(p_pelny * stopa_fp)
    pelny_suma_bez_chorobowego = pelny_emerytalna + pelny_rentowa + pelny_wypadkowa + pelny_fp
    pelny_suma_z_chorobowym = pelny_suma_bez_chorobowego + pelny_chorobowa

    # Preferencyjny ZUS (Mały ZUS Plus / 30% minimalnej)
    p_pref = params.podstawa_preferencyjny_zus
    pref_emerytalna = _rnd(p_pref * stopa_emerytalna)
    pref_rentowa = _rnd(p_pref * stopa_rentowa)
    pref_chorobowa = _rnd(p_pref * stopa_chorobowa)
    pref_wypadkowa = _rnd(p_pref * stopa_wypadkowa)
    pref_fp = Decimal("0.00")  # zwolnienie z FP poniżej minimalnego wynagrodzenia
    pref_suma_bez_chorobowego = pref_emerytalna + pref_rentowa + pref_wypadkowa
    pref_suma_z_chorobowym = pref_suma_bez_chorobowego + pref_chorobowa

    # Zdrowotna ryczałt (3 progi)
    baza_zdrowotna = params.przecietne_wynagrodzenie_zdrowotna
    prog1_podstawa = _rnd(baza_zdrowotna * Decimal("0.60"))
    prog1_kwota = _rnd(prog1_podstawa * stopa_zdrowotna)
    prog1_odliczenie = _rnd(prog1_kwota * Decimal("0.50"))

    prog2_podstawa = _rnd(baza_zdrowotna * Decimal("1.00"))
    prog2_kwota = _rnd(prog2_podstawa * stopa_zdrowotna)
    prog2_odliczenie = _rnd(prog2_kwota * Decimal("0.50"))

    prog3_podstawa = _rnd(baza_zdrowotna * Decimal("1.80"))
    prog3_kwota = _rnd(prog3_podstawa * stopa_zdrowotna)
    prog3_odliczenie = _rnd(prog3_kwota * Decimal("0.50"))

    return {
        "rok": params.rok,
        "podstawa_pelny_zus": params.podstawa_pelny_zus,
        "podstawa_preferencyjny_zus": params.podstawa_preferencyjny_zus,
        "przecietne_wynagrodzenie_zdrowotna": params.przecietne_wynagrodzenie_zdrowotna,
        "zrodlo": params.zrodlo,
        "ostrzezenie": params.ostrzezenie,
        "pelny": {
            "podstawa": p_pelny,
            "emerytalna": pelny_emerytalna,
            "rentowa": pelny_rentowa,
            "chorobowa": pelny_chorobowa,
            "wypadkowa": pelny_wypadkowa,
            "fundusz_pracy": pelny_fp,
            "suma_bez_chorobowego": pelny_suma_bez_chorobowego,
            "suma_z_chorobowym": pelny_suma_z_chorobowym,
        },
        "preferencyjny": {
            "podstawa": p_pref,
            "emerytalna": pref_emerytalna,
            "rentowa": pref_rentowa,
            "chorobowa": pref_chorobowa,
            "wypadkowa": pref_wypadkowa,
            "fundusz_pracy": pref_fp,
            "suma_bez_chorobowego": pref_suma_bez_chorobowego,
            "suma_z_chorobowym": pref_suma_z_chorobowym,
        },
        "zdrowotna_ryczalt": [
            {
                "prog_nazwa": "I próg (przychody roczne do 60 000 zł)",
                "zakres": "≤ 60 000 zł",
                "mnoznik_bazy": "60%",
                "podstawa": prog1_podstawa,
                "stawka": "9%",
                "kwota_miesieczna": prog1_kwota,
                "odliczenie_50": prog1_odliczenie,
            },
            {
                "prog_nazwa": "II próg (przychody roczne 60 000 – 300 000 zł)",
                "zakres": "60 000 – 300 000 zł",
                "mnoznik_bazy": "100%",
                "podstawa": prog2_podstawa,
                "stawka": "9%",
                "kwota_miesieczna": prog2_kwota,
                "odliczenie_50": prog2_odliczenie,
            },
            {
                "prog_nazwa": "III próg (przychody roczne powyżej 300 000 zł)",
                "zakres": "> 300 000 zł",
                "mnoznik_bazy": "180%",
                "podstawa": prog3_podstawa,
                "stawka": "9%",
                "kwota_miesieczna": prog3_kwota,
                "odliczenie_50": prog3_odliczenie,
            },
        ],
    }


def get_zus_indicators(
    rok: str,
    profile_overrides: Optional[Dict[str, Any]] = None,
    try_online: bool = False,
    cache_path: Optional[Path] = None,
) -> ZUSMacroParams:
    """
    Pobiera komplet wskaźników ZUS dla danego roku z uwzględnieniem priorytetów:
    1. Nadpisanie w profilu firmy (jeśli podano).
    2. Ręcznie wprowadzone / zweryfikowane wskaźniki z cache (ZWERYFIKOWANE, WPROWADZONE_RECZNIE).
    3. Baza oficjalnych wskaźników wbudowanych (OFICJALNE_WSKAZNIKI).
    4. Trwały cache na dysku (data/wskazniki_zus_cache.json) z poprzednich udanych pobrań.
    5. Próba pobrania online (jeśli włączona flaga try_online) i zapis do cache.
    6. Bezpieczny fallback z wyliczoną prognozą szacunkową i alertem ostrzegawczym.
    """
    rok_str = str(rok)

    # 1. Sprawdzenie nadpisań w profilu firmy
    if profile_overrides:
        custom_spol = profile_overrides.get("custom_podstawa_spoleczne")
        custom_zdrow = profile_overrides.get("custom_przecietne_wynagrodzenie")
        if custom_spol or custom_zdrow:
            base = OFICJALNE_WSKAZNIKI.get(rok_str) or OFICJALNE_WSKAZNIKI["2026"]
            return ZUSMacroParams(
                rok=rok_str,
                podstawa_pelny_zus=Decimal(str(custom_spol)) if custom_spol else base.podstawa_pelny_zus,
                podstawa_preferencyjny_zus=base.podstawa_preferencyjny_zus,
                przecietne_wynagrodzenie_zdrowotna=Decimal(str(custom_zdrow)) if custom_zdrow else base.przecietne_wynagrodzenie_zdrowotna,
                zrodlo="PROFIL_UZYTKOWNIKA",
                ostrzezenie="Zastosowano ręczne nadpisanie wskaźników ZUS z profilu firmy.",
            )

    # 2. Sprawdzenie trwałego cache (jeśli wpis został zweryfikowany lub ręcznie wprowadzony przez użytkownika)
    cached = load_from_cache(rok_str, cache_path=cache_path)
    if cached and cached.zrodlo in ("WPROWADZONE_RECZNIE", "ZWERYFIKOWANE", "PROFIL_UZYTKOWNIKA"):
        return cached

    # 3. Oficjalna zatwierdzona baza wiedzy
    if rok_str in OFICJALNE_WSKAZNIKI:
        return OFICJALNE_WSKAZNIKI[rok_str]

    # 4. Trwały lokalny cache dyskowy (np. pobrane wcześniej online lub inne)
    if cached:
        return cached

    # 5. Próba pobrania z internetu
    if try_online:
        online = fetch_online_indicators(rok_str)
        if online:
            save_to_cache(online, cache_path=cache_path)
            return online

    # 6. Fallback: Estymacja na podstawie ostatniego znanego roku z alertem ostrzegawczym
    ostatni_znany = max(OFICJALNE_WSKAZNIKI.keys())
    wzorzec = OFICJALNE_WSKAZNIKI[ostatni_znany]
    
    # Szacunkowy roczny wzrost płac ~6.5%
    lata_roznicy = int(rok_str) - int(ostatni_znany)
    mnoznik = (Decimal("1.065")) ** max(1, lata_roznicy)
    
    szacunek_spol = (wzorzec.podstawa_pelny_zus * mnoznik).quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    szacunek_pref = (wzorzec.podstawa_preferencyjny_zus * mnoznik).quantize(Decimal("1.00"), rounding=ROUND_HALF_UP)
    szacunek_zdrow = (wzorzec.przecietne_wynagrodzenie_zdrowotna * mnoznik).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return ZUSMacroParams(
        rok=rok_str,
        podstawa_pelny_zus=szacunek_spol,
        podstawa_preferencyjny_zus=szacunek_pref,
        przecietne_wynagrodzenie_zdrowotna=szacunek_zdrow,
        zrodlo="PROGNOZA_SZACOWANA",
        ostrzezenie=(
            f"⚠️ Uwaga: Zastosowano prognozowane wskaźniki ZUS dla roku {rok_str} "
            f"(podstawa zdrowotnej: {szacunek_zdrow} zł). "
            f"Brak oficjalnego komunikatu Prezesa GUS – kwota składki zdrowotnej może ulec drobnej korekcie po publikacji obwieszczenia."
        ),
    )

