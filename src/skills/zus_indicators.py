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
#   * podstawa pełny ZUS (60% prognozowanego przeciętnego wynagrodzenia): 5 304.00 zł
#   * podstawa preferencyjny ZUS (30% płacy minimalnej): 1 440.00 zł
#   * przeciętne wynagrodzenie w IV kw. do składki zdrowotnej: 9 008.11 zł
#     (co przy 9% daje składkę: 810.73 zł dla II progu 60k-300k zł, 486.44 zł dla I progu, 1459.31 zł dla III progu)
# - 2025:
#   * podstawa pełny ZUS: 4 694.40 zł
#   * podstawa preferencyjny ZUS: 1 399.80 zł
#   * przeciętne wynagrodzenie w IV kw. do zdrowotnej: 8 500.00 zł
OFICJALNE_WSKAZNIKI: Dict[str, ZUSMacroParams] = {
    "2026": ZUSMacroParams(
        rok="2026",
        podstawa_pelny_zus=Decimal("5304.00"),
        podstawa_preferencyjny_zus=Decimal("1440.00"),
        przecietne_wynagrodzenie_zdrowotna=Decimal("9008.11"),
        zrodlo="OFICJALNE_GUS",
        ostrzezenie=None,
    ),
    "2025": ZUSMacroParams(
        rok="2025",
        podstawa_pelny_zus=Decimal("4694.40"),
        podstawa_preferencyjny_zus=Decimal("1399.80"),
        przecietne_wynagrodzenie_zdrowotna=Decimal("8500.00"),
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


def get_zus_indicators(
    rok: str,
    profile_overrides: Optional[Dict[str, Any]] = None,
    try_online: bool = False,
    cache_path: Optional[Path] = None,
) -> ZUSMacroParams:
    """
    Pobiera komplet wskaźników ZUS dla danego roku z uwzględnieniem priorytetów:
    1. Nadpisanie w profilu firmy (jeśli podano).
    2. Baza oficjalnych wskaźników wbudowanych (OFICJALNE_WSKAZNIKI).
    3. Trwały cache na dysku (data/wskazniki_zus_cache.json) z poprzednich udanych pobrań.
    4. Próba pobrania online (jeśli włączona flaga try_online) i zapis do cache.
    5. Bezpieczny fallback z wyliczoną prognozą szacunkową i alertem ostrzegawczym.
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

    # 2. Oficjalna zatwierdzona baza wiedzy
    if rok_str in OFICJALNE_WSKAZNIKI:
        return OFICJALNE_WSKAZNIKI[rok_str]

    # 3. Trwały lokalny cache dyskowy
    cached = load_from_cache(rok_str, cache_path=cache_path)
    if cached:
        return cached

    # 4. Próba pobrania z internetu
    if try_online:
        online = fetch_online_indicators(rok_str)
        if online:
            save_to_cache(online, cache_path=cache_path)
            return online

    # 4. Fallback: Estymacja na podstawie ostatniego znanego roku z alertem ostrzegawczym
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

