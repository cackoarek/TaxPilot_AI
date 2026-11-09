"""
Modele danych profilu firmy podatnika i konfiguracji podatkowo-składkowej.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
import json
import re

from src.config import FIRMY_DIR


class FormaOpodatkowania(str, Enum):
    RYCZALT = "RYCZALT"
    LINIOWY = "LINIOWY"
    SKALA = "SKALA"


class TypZUS(str, Enum):
    ULGA_NA_START = "ULGA_NA_START"
    MALY_ZUS_PLUS = "MALY_ZUS_PLUS"
    PELNY_ZUS = "PELNY_ZUS"


@dataclass
class ZUSConfig:
    typ: TypZUS = TypZUS.PELNY_ZUS
    chorobowe_dobrowolne: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ZUSConfig":
        return cls(
            typ=TypZUS(data.get("typ", TypZUS.PELNY_ZUS)),
            chorobowe_dobrowolne=bool(data.get("chorobowe_dobrowolne", True)),
        )


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
        )

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["forma_opodatkowania"] = self.forma_opodatkowania.value
        res["zus"]["typ"] = self.zus.typ.value
        res["ksef"] = self.ksef.to_dict()
        return res

    def set_ksef_token(self, token: str, srodowisko: Optional[str] = None) -> Path:
        """Zapisuje token KSeF w konfiguracji firmy i utrwala w profil.json."""
        self.ksef.token = token.strip()
        if srodowisko:
            self.ksef.srodowisko = srodowisko.upper()
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
        clean_nip = re.sub(r"[^0-9]", "", nip)
        if not FIRMY_DIR.exists():
            return None
        for path in FIRMY_DIR.iterdir():
            if path.is_dir() and path.name.startswith(clean_nip):
                profil_path = path / "profil.json"
                if profil_path.exists():
                    return cls.load_from_dir(path)
        return None
