"""
Modele danych profilu firmy podatnika i konfiguracji podatkowo-składkowej.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import json
import re

from src.config import FIRMY_DIR


class FormaOpodatkowania(str, Enum):
    RYCZALT = "RYCZALT"
    LINIOWY = "LINIOWY"
    SKALA = "SKALA"


class TypZUS(str, Enum):
    ULGA_NA_START = "ULGA_NA_START"
    TYLKO_ZDROWOTNA = "TYLKO_ZDROWOTNA"
    MALY_ZUS_PLUS = "MALY_ZUS_PLUS"
    PELNY_ZUS = "PELNY_ZUS"


@dataclass
class ZUSConfig:
    typ: TypZUS = TypZUS.PELNY_ZUS
    chorobowe_dobrowolne: bool = True
    zasada_odliczen: str = "MEMORIALOWA"  # "MEMORIALOWA" (domyślna) | "KASOWA" (biura rachunkowe)
    metoda_zdrowotna: str = "BIEZACA"  # "BIEZACA" (domyślna) | "UPROSZCZONA_UBIEGLY_ROK" (art. 81 ust. 2h)
    prog_zdrowotnej_uproszczony: str = "60k-300k"  # "<60k" | "60k-300k" | ">300k"
    historia_typow: Dict[str, str] = field(default_factory=dict)  # np. {"2026-01": "TYLKO_ZDROWOTNA", "2026-04": "PELNY_ZUS"}

    def get_typ_for_period(self, rok: str, miesiac: str) -> TypZUS:
        """Zwraca właściwy typ ZUS dla danego okresu YYYY-MM na podstawie historii zmian."""
        if not self.historia_typow:
            return self.typ
        try:
            period_key = f"{rok}-{int(miesiac):02d}"
        except (ValueError, TypeError):
            period_key = f"{rok}-{miesiac}"
        applicable = None
        for k in sorted(self.historia_typow.keys()):
            if k <= period_key:
                applicable = self.historia_typow[k]
        if applicable:
            try:
                return TypZUS(applicable)
            except ValueError:
                pass
        return self.typ

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ZUSConfig":
        return cls(
            typ=TypZUS(data.get("typ", TypZUS.PELNY_ZUS)),
            chorobowe_dobrowolne=bool(data.get("chorobowe_dobrowolne", True)),
            zasada_odliczen=str(data.get("zasada_odliczen", "MEMORIALOWA")),
            metoda_zdrowotna=str(data.get("metoda_zdrowotna", "BIEZACA")),
            prog_zdrowotnej_uproszczony=str(data.get("prog_zdrowotnej_uproszczony", "60k-300k")),
            historia_typow=dict(data.get("historia_typow", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "typ": self.typ.value,
            "chorobowe_dobrowolne": self.chorobowe_dobrowolne,
            "zasada_odliczen": self.zasada_odliczen,
            "metoda_zdrowotna": self.metoda_zdrowotna,
            "prog_zdrowotnej_uproszczony": self.prog_zdrowotnej_uproszczony,
        }
        if self.historia_typow:
            res["historia_typow"] = self.historia_typow
        return res


@dataclass
class KSeFConfig:
    srodowisko: str = "PROD"  # TEST | PROD
    token: Optional[str] = None
    token_env_var: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KSeFConfig":
        return cls(
            srodowisko=data.get("srodowisko", "PROD"),
            token=data.get("token"),
            token_env_var=data.get("token_env_var"),
        )

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "srodowisko": self.srodowisko,
        }
        if self.token is not None:
            res["token"] = self.token
        if self.token_env_var is not None:
            res["token_env_var"] = self.token_env_var
        return res


@dataclass
class CompanyProfile:
    nip: str
    nazwa: str
    forma_opodatkowania: FormaOpodatkowania = FormaOpodatkowania.RYCZALT
    domyslna_stawka_ryczaltu: float = 0.12  # np. 0.12 dla IT
    platnik_vat: bool = True
    zus: ZUSConfig = field(default_factory=ZUSConfig)
    ksef: KSeFConfig = field(default_factory=KSeFConfig)
    katalog_nazwa: Optional[str] = None
    kody_pkd: List[str] = field(default_factory=list)
    regon: Optional[str] = None
    adres: Optional[str] = None
    llm: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Wyczyszczenie NIP z myślników i spacji
        self.nip = re.sub(r"[^0-9]", "", self.nip)
        if not self.katalog_nazwa:
            nazwa_safe = re.sub(r"[^\w\-_]", "_", self.nazwa)
            self.katalog_nazwa = f"{self.nip}-{nazwa_safe}"

    @property
    def katalog_firmy(self) -> Path:
        return FIRMY_DIR / (self.katalog_nazwa or self.nip)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyProfile":
        zus_data = data.get("zus", {})
        ksef_data = data.get("ksef", {})
        return cls(
            nip=str(data["nip"]),
            nazwa=data["nazwa"],
            katalog_nazwa=data.get("katalog_nazwa"),
            forma_opodatkowania=FormaOpodatkowania(data.get("forma_opodatkowania", FormaOpodatkowania.RYCZALT)),
            domyslna_stawka_ryczaltu=float(data.get("domyslna_stawka_ryczaltu", 0.12)),
            platnik_vat=bool(data.get("platnik_vat", True)),
            zus=ZUSConfig.from_dict(zus_data),
            ksef=KSeFConfig.from_dict(ksef_data),
            kody_pkd=list(data.get("kody_pkd", [])),
            regon=data.get("regon"),
            adres=data.get("adres"),
            llm=dict(data.get("llm", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["forma_opodatkowania"] = self.forma_opodatkowania.value
        res["zus"]["typ"] = self.zus.typ.value
        res["ksef"] = self.ksef.to_dict()
        res["llm"] = self.llm
        return res

    def set_ksef_token(self, token: str, srodowisko: Optional[str] = None) -> Path:
        """Zapisuje token KSeF w konfiguracji firmy i utrwala w profil.json."""
        self.ksef.token = token.strip()
        if srodowisko:
            self.ksef.srodowisko = srodowisko.upper()
        return self.save()

    def update_tax_and_zus_settings(
        self,
        domyslna_stawka_ryczaltu: float,
        typ_zus: TypZUS,
        chorobowe_dobrowolne: bool,
        platnik_vat: bool,
        zasada_odliczen: Optional[str] = None,
        metoda_zdrowotna: Optional[str] = None,
        prog_zdrowotnej_uproszczony: Optional[str] = None,
    ) -> Path:
        """Aktualizuje zmienne parametry podatkowo-składkowe firmy i zapisuje w profil.json."""
        self.domyslna_stawka_ryczaltu = float(domyslna_stawka_ryczaltu)
        self.zus.typ = typ_zus
        self.zus.chorobowe_dobrowolne = bool(chorobowe_dobrowolne)
        self.platnik_vat = bool(platnik_vat)
        if zasada_odliczen:
            self.zus.zasada_odliczen = zasada_odliczen
        if metoda_zdrowotna:
            self.zus.metoda_zdrowotna = metoda_zdrowotna
        if prog_zdrowotnej_uproszczony:
            self.zus.prog_zdrowotnej_uproszczony = prog_zdrowotnej_uproszczony
        return self.save()

    def set_llm_config(self, provider: str, model: Optional[str] = None) -> Path:
        """Zapisuje konfigurację silnika AI dla firmy i utrwala w profil.json."""
        self.llm = {
            "provider": provider.lower().strip(),
            "model": (model or "").strip(),
        }
        return self.save()

    def save(self) -> Path:
        target_dir = self.katalog_firmy
        target_dir.mkdir(parents=True, exist_ok=True)
        profil_path = target_dir / "profil.json"
        with open(profil_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return profil_path

    @classmethod
    def load_from_dir(cls, directory_path: Path) -> "CompanyProfile":
        profil_path = directory_path / "profil.json"
        if not profil_path.exists():
            raise FileNotFoundError(f"Brak pliku profil.json w katalogu: {directory_path}")
        with open(profil_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def load_by_nip(cls, nip: str) -> Optional["CompanyProfile"]:
        if not FIRMY_DIR.exists():
            return None
        # 1. Dokładna ścieżka lub nazwa katalogu
        target = FIRMY_DIR / nip
        if target.is_dir() and (target / "profil.json").exists():
            return cls.load_from_dir(target)
        # 2. Jeśli podano nazwę ze słowem kluczowym (np. CloudTech_Test)
        for path in FIRMY_DIR.iterdir():
            if path.is_dir() and nip.lower() in path.name.lower() and (path / "profil.json").exists():
                return cls.load_from_dir(path)
        # 3. Wyszukiwanie po samym numerze NIP
        clean_nip = re.sub(r"[^0-9]", "", nip)
        if not clean_nip:
            return None
        for path in sorted(FIRMY_DIR.iterdir(), reverse=True):
            if path.is_dir() and path.name.startswith(clean_nip):
                profil_path = path / "profil.json"
                if profil_path.exists():
                    return cls.load_from_dir(path)
        return None


def initialize_company(
    nip: str,
    nazwa: Optional[str] = None,
    adres: Optional[str] = None,
    regon: Optional[str] = None,
    forma_opodatkowania: Union[str, FormaOpodatkowania] = FormaOpodatkowania.RYCZALT,
    domyslna_stawka_ryczaltu: float = 0.12,
    platnik_vat: bool = True,
    zus_typ: Union[str, TypZUS] = TypZUS.PELNY_ZUS,
    chorobowe_dobrowolne: bool = True,
    kody_pkd: Optional[List[str]] = None,
    srodowisko_ksef: str = "PROD",
    token_ksef: Optional[str] = None,
    auto_fetch: bool = True,
    ceidg_token: Optional[str] = None,
    force: bool = False,
) -> CompanyProfile:
    """
    Inicjalizuje profil nowej firmy, pobiera dane z rejestrów (Biała Lista MF / CEIDG),
    tworzy profil.json, strukturę katalogów faktur i rozliczeń oraz wstępne reguły podatkowe.
    """
    from datetime import datetime
    clean_nip = re.sub(r"[^0-9]", "", nip or "")
    if len(clean_nip) != 10:
        raise ValueError(f"Nieprawidłowy NIP ({nip}). Polski NIP musi składać się dokładnie z 10 cyfr.")

    existing = CompanyProfile.load_by_nip(clean_nip)
    if existing and not force:
        raise ValueError(f"Firma z NIP {clean_nip} już istnieje w systemie ({existing.nazwa}).")

    final_nazwa = nazwa.strip() if nazwa and nazwa.strip() else None
    final_adres = adres.strip() if adres and adres.strip() else None
    final_regon = regon.strip() if regon and regon.strip() else None
    final_pkd = list(kody_pkd) if kody_pkd else []
    final_vat = platnik_vat

    if auto_fetch:
        try:
            from src.level_1_ingestion.company_fetcher import CompanyFetcher
            public_data = CompanyFetcher.fetch_company_info(clean_nip, ceidg_token=ceidg_token)
            if public_data.get("nazwa") and not final_nazwa:
                final_nazwa = public_data["nazwa"]
            if public_data.get("adres") and not final_adres:
                final_adres = public_data["adres"]
            if public_data.get("regon") and not final_regon:
                final_regon = public_data["regon"]
            if "platnik_vat" in public_data and platnik_vat is None:
                final_vat = bool(public_data["platnik_vat"])
            if public_data.get("kody_pkd") and not final_pkd:
                final_pkd = list(public_data["kody_pkd"])
        except Exception:
            pass

    if not final_nazwa:
        final_nazwa = f"Firma {clean_nip}"

    if isinstance(forma_opodatkowania, str):
        forma_enum = FormaOpodatkowania(forma_opodatkowania.upper())
    else:
        forma_enum = forma_opodatkowania

    if isinstance(zus_typ, str):
        zus_enum = TypZUS(zus_typ.upper())
    else:
        zus_enum = zus_typ

    profile = CompanyProfile(
        nip=clean_nip,
        nazwa=final_nazwa,
        forma_opodatkowania=forma_enum,
        domyslna_stawka_ryczaltu=float(domyslna_stawka_ryczaltu),
        platnik_vat=bool(final_vat),
        zus=ZUSConfig(typ=zus_enum, chorobowe_dobrowolne=bool(chorobowe_dobrowolne)),
        ksef=KSeFConfig(srodowisko=srodowisko_ksef.upper(), token=token_ksef.strip() if token_ksef else None),
        kody_pkd=final_pkd,
        regon=final_regon,
        adres=final_adres,
    )
    profile.save()

    # Wstępne reguły kosztowe
    try:
        from src.skills.cost_classifier import RegulyKosztoweFirmy, RegulaPozycji, KwalifikacjaKosztu
        reguly = RegulyKosztoweFirmy(nip_firmy=clean_nip)
        reguly.reguly_globalne.append(
            RegulaPozycji(wzorzec="paliwo", kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50, uzasadnienie="Paliwo do pojazdu osobowego (art. 86a ustawy o VAT)")
        )
        is_it = any(code.startswith(("62.", "58.2", "63.")) for code in final_pkd)
        if is_it or not final_pkd:
            reguly.reguly_globalne.extend([
                RegulaPozycji(wzorzec="hosting", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Infrastruktura serwerowa i chmurowa"),
                RegulaPozycji(wzorzec="cloud", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Usługi chmurowe"),
                RegulaPozycji(wzorzec="serwer", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Serwery i bazy danych"),
                RegulaPozycji(wzorzec="oprogramowanie", kwalifikacja=KwalifikacjaKosztu.FIRMOWY_100, uzasadnienie="Licencje na oprogramowanie"),
            ])
        reguly.save(profile)
    except Exception:
        pass

    # Puste reguły sprzedaży
    try:
        from src.level_2_bookkeeping.ledger import RegulySprzedazyFirmy
        reguly_sprz = RegulySprzedazyFirmy(nip_firmy=clean_nip)
        reguly_sprz.save(profile)
    except Exception:
        pass

    # Inicjalizacja struktury katalogów na faktury i rozliczenia
    cur_year = datetime.now().year
    years_to_init = sorted(list(set([str(cur_year), "2026", "2027"])))
    for y in years_to_init:
        for m in range(1, 13):
            m_str = f"{m:02d}"
            for kierunek in ["sprzedaz", "koszty"]:
                for sub in ["ksef", "non-ksef-raw", "non-ksef-extracted"]:
                    (profile.katalog_firmy / "faktury" / y / m_str / kierunek / sub).mkdir(parents=True, exist_ok=True)
    (profile.katalog_firmy / "rozliczenia").mkdir(parents=True, exist_ok=True)
    (profile.katalog_firmy / "weryfikacje").mkdir(parents=True, exist_ok=True)

    return profile
