"""
src/core/backup.py
Moduł tworzenia i bezpiecznego przywracania kopii zapasowych firmowych (OPS-1).
Zapewnia:
- pakowanie katalogu firmy do archiwum .tar.gz ze stemplem czasowym
- generowanie sumy kontrolnej SHA-256
- restrykcyjne uprawnienia 0600 dla kopii zapasowych
- ochronę przed podatnością TarSlip / Path Traversal (CWE-22) podczas odzyskiwania
- atomową weryfikację integralności przed odtworzeniem
"""

import hashlib
import os
import re
import secrets
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union

from src.config import FIRMY_DIR
from src.core.company import CompanyProfile, migrate_data_permissions
from src.core.io import atomic_write_text
from src.logging_config import get_logger

logger = get_logger("taxpilot.backup")


def calculate_file_sha256(file_path: Union[str, Path]) -> str:
    """Oblicza sumę kontrolną SHA-256 pliku."""
    path = Path(file_path)
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def create_company_backup(
    profile: CompanyProfile,
    output_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Path, Path]:
    """
    Tworzy kompletną, spójną kopię zapasową danych firmy w formacie .tar.gz (OPS-1).
    Generuje również plik sumy kontrolnej .sha256.
    Zwraca krotkę (archive_path, sha256_path).
    """
    source_dir = profile.katalog_firmy
    if not source_dir.exists():
        raise FileNotFoundError(f"Katalog firmy nie istnieje: {source_dir}")

    # Domyślny katalog na backupy
    if output_dir is not None:
        target_dir = Path(output_dir).resolve()
    else:
        target_dir = (source_dir.parent / "backups").resolve()

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_dir.chmod(0o700)
    except OSError:
        pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_nip = re.sub(r"[^0-9]", "", profile.nip)
    archive_name = f"backup_{clean_nip}_{timestamp}.tar.gz"
    archive_path = target_dir / archive_name
    sha256_path = target_dir / f"{archive_name}.sha256"

    # Tworzenie archiwum tar.gz z wykluczeniem plików tymczasowych i blokad
    with tarfile.open(archive_path, "w:gz") as tar:
        for root, dirs, files in os.walk(source_dir):
            root_path = Path(root)
            # Pomijaj tymczasowe katalogi __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".tmp")]

            for file in files:
                # Pomijaj pliki blokad i tymczasowe
                if file.endswith((".lock", ".tmp")):
                    continue
                file_full = root_path / file
                arcname = str(Path(source_dir.name) / file_full.relative_to(source_dir))
                tar.add(file_full, arcname=arcname)

    # Restrykcyjne uprawnienia pliku archiwum (0600)
    try:
        archive_path.chmod(0o600)
    except OSError:
        pass

    # Obliczenie sumy SHA-256 i zapis pliku sumy kontrolnej
    digest = calculate_file_sha256(archive_path)
    sha_content = f"{digest}  {archive_name}\n"
    atomic_write_text(sha256_path, sha_content, mode=0o600)

    logger.info(
        "Utworzono kopię zapasową firmy %s (NIP %s): %s (SHA-256: %s)",
        profile.nazwa,
        profile.nip,
        archive_path.name,
        digest,
    )
    return archive_path, sha256_path


def verify_backup_integrity(archive_path: Union[str, Path]) -> Tuple[bool, str]:
    """
    Weryfikuje spójność pliku archiwum kopii zapasowej oraz zgodność sumy SHA-256 (jeśli dostępna).
    Zwraca (is_valid, message).
    """
    path = Path(archive_path).resolve()
    if not path.exists():
        return False, f"Plik archiwum nie istnieje: {path}"

    # 1. Weryfikacja pliku .sha256 jeśli istnieje
    sha_file = path.parent / f"{path.name}.sha256"
    if sha_file.exists():
        try:
            content = sha_file.read_text(encoding="utf-8").strip()
            expected_digest = content.split()[0].lower()
            actual_digest = calculate_file_sha256(path).lower()
            if not secrets.compare_digest(expected_digest, actual_digest):
                return False, f"Niezgodność sumy kontrolnej SHA-256 (oczekiwano: {expected_digest}, obliczono: {actual_digest})"
        except Exception as exc:
            return False, f"Błąd weryfikacji sumy kontrolnej SHA-256: {exc}"

    # 2. Sprawdzenie integralności nagłówków i zawartości tar.gz
    try:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar.getmembers():
                # Inspekcja bezpieczeństwa TarSlip (CWE-22)
                p = Path(member.name)
                if p.is_absolute() or ".." in p.parts:
                    return False, f"Wykryto niebezpieczną ścieżkę w archiwum (TarSlip): {member.name}"
                if member.islnk() or member.issym():
                    target_p = Path(member.linkname)
                    if target_p.is_absolute() or ".." in target_p.parts:
                        return False, f"Wykryto niebezpieczne dowiązanie w archiwum: {member.linkname}"
    except Exception as exc:
        return False, f"Uszkodzone archiwum tar.gz: {exc}"

    return True, "Integralność archiwum potwierdzona"


def restore_company_backup(
    archive_path: Union[str, Path],
    target_base_dir: Optional[Union[str, Path]] = None,
    verify_sha: bool = True,
) -> CompanyProfile:
    """
    Bezpiecznie przywraca dane firmy z archiwum kopii zapasowej (OPS-1).
    Weryfikuje sumę SHA-256, chroni przed atakiem TarSlip (CWE-22) oraz
    wymusza restrykcyjne uprawnienia 0700/0600 po rozpakowaniu.
    """
    path = Path(archive_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku kopii zapasowej: {path}")

    # 1. Weryfikacja integralności i bezpieczeństwa archiwum
    if verify_sha:
        is_valid, msg = verify_backup_integrity(path)
        if not is_valid:
            raise ValueError(f"Weryfikacja integralności kopii zapasowej nie powiodła się: {msg}")

    # 2. Ustalenie docelowego katalogu bazowego (domyślnie FIRMY_DIR)
    dest_base = Path(target_base_dir).resolve() if target_base_dir is not None else FIRMY_DIR.resolve()
    dest_base.mkdir(parents=True, exist_ok=True)

    extracted_root_dirs = set()
    with tarfile.open(path, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            # Rygorystyczna ochrona TarSlip: sprawdzanie czy ścieżka nie ucieka z katalogu bazowego
            norm_name = Path(member.name).as_posix()
            if norm_name.startswith("/") or ".." in norm_name.split("/"):
                raise ValueError(f"Odrzucono niebezpieczną ścieżkę w archiwum: {member.name}")

            # Wyznaczenie głównego katalogu firmy z archiwum
            root_part = Path(member.name).parts[0]
            extracted_root_dirs.add(root_part)

            # Bezpieczna ekstrakcja elementu
            tar.extract(member, path=dest_base)

    if not extracted_root_dirs:
        raise ValueError("Archiwum jest puste")

    # Przywrócony katalog firmy
    primary_dir_name = sorted(extracted_root_dirs)[0]
    restored_company_dir = dest_base / primary_dir_name

    # 3. Wymuszenie restrykcyjnych uprawnień chmod 700/600 (SEC-4, PERM-1)
    migrate_data_permissions(dest_base)

    # 4. Sprawdzenie profilu i załadowanie CompanyProfile
    profile = CompanyProfile.load_from_dir(restored_company_dir)
    logger.info(
        "Pomyślnie przywrócono firmę %s (NIP %s) z archiwum %s",
        profile.nazwa,
        profile.nip,
        path.name,
    )
    return profile
