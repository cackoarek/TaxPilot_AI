"""
src/level_1_ingestion/extraction_service.py
Serwis zarządzania ekstrakcją i odczytywaniem nieprzetworzonych faktur (AI Vision / OCR).
Wykrywa faktury, których nie udało się odczytać automatycznie (kwoty 0.00 zł, brak NIP),
zarządza asynchronicznym zadaniem w tle oraz raportuje status procesu.
"""
import asyncio
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.logging_config import get_logger
from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor

logger = get_logger("taxpilot.extraction_service")

# Pamięć podręczna uruchomionych zadań w tle per klucz (nip, rok, miesiac)
_RUNNING_TASKS: Dict[str, Dict[str, Any]] = {}


class ExtractionService:
    """
    Serwis detekcji i ekstrakcji nieprzetworzonych dokumentów w tle.
    """

    @classmethod
    def _get_key(cls, profile: CompanyProfile, rok: str, miesiac: str) -> str:
        return f"{profile.nip}_{rok}_{miesiac}"

    @classmethod
    def _get_status_file(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Path:
        m_str = str(miesiac).zfill(2)
        r_str = str(rok)
        month_dir = profile.katalog_firmy / "faktury" / r_str / m_str
        month_dir.mkdir(parents=True, exist_ok=True)
        return month_dir / ".extraction_status.json"

    @classmethod
    def get_unprocessed_invoices(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
    ) -> List[Dict[str, Any]]:
        """
        Wyszukuje faktury z danego okresu, których nie udało się prawidłowo odczytać:
        - kwota brutto wynosi 0.00 zł,
        - sprzedawca ma NIP 0000000000 lub brak NIP,
        - opis pozycji zawiera '(do weryfikacji kwot)',
        - pliki surowe w non-ksef-raw bez poprawnego pliku JSON.
        """
        unprocessed: List[Dict[str, Any]] = []
        if not profile:
            return unprocessed

        try:
            invoices = InvoiceStorage.list_invoices(profile, rok, miesiac)
        except Exception as e:
            logger.warning("Błąd odczytu faktur dla %s-%s: %s", rok, miesiac, e)
            return unprocessed

        for inv in invoices:
            is_unprocessed = False
            reasons = []

            # 1. Zerowa kwota
            if inv.suma_brutto == Decimal("0.00") and inv.suma_netto == Decimal("0.00"):
                is_unprocessed = True
                reasons.append("kwota 0,00 zł")

            # 2. Brak identyfikatora sprzedawcy / domyślny NIP
            if inv.sprzedawca.nip in ("0000000000", "", None):
                is_unprocessed = True
                reasons.append("brak NIP sprzedawcy")

            # 3. Flaga do weryfikacji kwot w pozycjach
            if any("(do weryfikacji kwot)" in (p.opis or "") for p in inv.pozycje):
                is_unprocessed = True
                reasons.append("wymaga weryfikacji kwot")

            # 4. Sprawdzenie czy numer odpowiada nazwie pliku fallback
            if inv.plik_zrodlowy and inv.numer == Path(inv.plik_zrodlowy).stem and inv.suma_brutto == Decimal("0.00"):
                is_unprocessed = True
                if "dokument nierozpoznany" not in reasons:
                    reasons.append("dokument nierozpoznany")

            if is_unprocessed:
                typ_label = "Koszty" if inv.typ == InvoiceType.KOSZT else "Sprzedaż"
                unprocessed.append({
                    "numer": inv.numer,
                    "plik": inv.plik_zrodlowy or inv.numer,
                    "sprzedawca": inv.sprzedawca.nazwa,
                    "typ": typ_label,
                    "reasons": reasons,
                    "powod_skrot": ", ".join(reasons),
                })

        # Sprawdzenie czy w folderach non-ksef-raw są pliki, które nie zostały wyekstrahowane w ogóle
        for typ_enum, typ_label in [(InvoiceType.KOSZT, "Koszty"), (InvoiceType.SPRZEDAZ, "Sprzedaż")]:
            raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=typ_enum)
            ext_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=typ_enum)
            if raw_dir.exists():
                for f in raw_dir.iterdir():
                    if f.is_file() and not f.name.endswith(".PRZENIESIONO.txt") and not f.name.startswith("."):
                        json_counterpart = ext_dir / f"{f.stem}.json"
                        if not json_counterpart.exists():
                            # Sprawdź czy już nie ma na liście
                            if not any(u["plik"] == f.name for u in unprocessed):
                                unprocessed.append({
                                    "numer": f.stem,
                                    "plik": f.name,
                                    "sprzedawca": "Nieznany",
                                    "typ": typ_label,
                                    "reasons": ["brak przetworzenia JSON"],
                                    "powod_skrot": "brak przetworzenia JSON",
                                })

        return unprocessed

    @classmethod
    def get_task_status(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Dict[str, Any]:
        """Zwraca bieżący status zadania ekstrakcji."""
        if not profile:
            return {"status": "idle", "message": ""}

        key = cls._get_key(profile, rok, miesiac)
        if key in _RUNNING_TASKS:
            return _RUNNING_TASKS[key]

        status_file = cls._get_status_file(profile, rok, miesiac)
        if status_file.exists():
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ts_str = data.get("timestamp")
                    if ts_str and data.get("status") in ("completed", "error"):
                        dt = datetime.fromisoformat(ts_str)
                        if (datetime.now() - dt).total_seconds() > 30.0:
                            try:
                                status_file.unlink(missing_ok=True)
                            except Exception:
                                pass
                            return {"status": "idle", "message": ""}
                    return data
            except Exception:
                pass

        return {"status": "idle", "message": ""}

    @classmethod
    def set_task_status(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        status: str,
        message: str = "",
        processed_files: Optional[List[str]] = None,
        current: int = 0,
        total: int = 0,
        percent: int = 0,
        current_file: str = "",
    ) -> None:
        """Utrwala stan zadania ekstrakcji w pamięci i na dysku."""
        key = cls._get_key(profile, rok, miesiac)
        data = {
            "status": status,
            "message": message,
            "processed_files": processed_files or [],
            "current": current,
            "total": total,
            "percent": percent,
            "current_file": current_file,
            "timestamp": datetime.now().isoformat(),
        }
        _RUNNING_TASKS[key] = data

        try:
            status_file = cls._get_status_file(profile, rok, miesiac)
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Błąd zapisu pliku statusu ekstrakcji: %s", e)

    @classmethod
    def clear_task_status(cls, profile: CompanyProfile, rok: str, miesiac: str) -> None:
        """Resetuje status zadania z powrotem do 'idle'."""
        key = cls._get_key(profile, rok, miesiac)
        if key in _RUNNING_TASKS:
            del _RUNNING_TASKS[key]

        status_file = cls._get_status_file(profile, rok, miesiac)
        if status_file.exists():
            try:
                status_file.unlink()
            except Exception:
                pass

    @classmethod
    async def run_ai_extraction_job(cls, profile: CompanyProfile, rok: str, miesiac: str) -> None:
        """
        Zadanie asynchroniczne wykonywane w tle.
        Przetwarza wszystkie nierozpoznane faktury sekwencyjnie plik po pliku za pomocą AI Vision / OCR,
        z niezależnym limitem czasu per plik (timeout=90s) i raportowaniem postępu na żywo.
        """
        logger.info("Uruchamianie asynchronicznego zadania ekstrakcji AI dla %s (%s-%s)", profile.nazwa, rok, miesiac)

        try:
            unprocessed = cls.get_unprocessed_invoices(profile, rok, miesiac)
            total = len(unprocessed)
            if not unprocessed or total == 0:
                cls.set_task_status(
                    profile,
                    rok,
                    miesiac,
                    status="completed",
                    message="Wszystkie dokumenty są już prawidłowo przetworzone.",
                    current=0,
                    total=0,
                    percent=100,
                )
                return

            processed_names: List[str] = []
            failed_names: List[str] = []
            timeout_names: List[str] = []

            from src.level_1_ingestion.ai_document_extractor import AIDocumentExtractor

            for idx, item in enumerate(unprocessed, 1):
                fn = item["plik"]
                pct_start = int(((idx - 1) / total) * 100)
                cls.set_task_status(
                    profile,
                    rok,
                    miesiac,
                    status="running",
                    message=f"Przetwarzanie dokumentu {idx} z {total}: {fn}...",
                    processed_files=processed_names,
                    current=idx,
                    total=total,
                    percent=pct_start,
                    current_file=fn,
                )

                typ_str = item["typ"].lower()
                inv_type = InvoiceType.SPRZEDAZ if "sprzeda" in typ_str else InvoiceType.KOSZT
                raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=inv_type)
                file_path = raw_dir / fn
                if not file_path.exists():
                    alt_type = InvoiceType.KOSZT if inv_type == InvoiceType.SPRZEDAZ else InvoiceType.SPRZEDAZ
                    alt_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=alt_type)
                    if (alt_dir / fn).exists():
                        file_path = alt_dir / fn
                        inv_type = alt_type

                if not file_path.exists() or file_path.name.endswith(".PRZENIESIONO.txt"):
                    continue

                try:
                    logger.info("Ekstrakcja dokumentu (%d/%d): %s (niezależny timeout=100s)", idx, total, fn)
                    inv = await asyncio.wait_for(
                        AIDocumentExtractor.extract_file_async(
                            file_path, profile, rok, miesiac, invoice_type=inv_type
                        ),
                        timeout=100.0,
                    )
                    if (inv.suma_brutto > Decimal("0.00") or inv.suma_netto > Decimal("0.00")) and inv.sprzedawca.nip not in ("0000000000", "", None):
                        processed_names.append(fn)
                        logger.info("Pomyślnie wyekstrahowano dokument (%d/%d): %s (brutto=%s zł)", idx, total, fn, inv.suma_brutto)
                    else:
                        failed_names.append(fn)
                        logger.warning("Niepełne dane dla dokumentu (%d/%d): %s", idx, total, fn)
                except asyncio.TimeoutError:
                    logger.warning("Przekroczono limit czasu (100s) dla dokumentu (%d/%d): %s", idx, total, fn)
                    timeout_names.append(fn)
                except Exception as e:
                    logger.warning("Błąd ekstrakcji dokumentu (%d/%d): %s: %s", idx, total, fn, e)
                    failed_names.append(fn)

                pct_end = int((idx / total) * 100)
                cls.set_task_status(
                    profile,
                    rok,
                    miesiac,
                    status="running",
                    message=f"Ukończono analizę dokumentu {idx} z {total}: {fn}",
                    processed_files=processed_names,
                    current=idx,
                    total=total,
                    percent=pct_end,
                    current_file=fn,
                )

            if processed_names:
                msg = (
                    f"Pomyślnie wyciągnięto dane z {len(processed_names)} z {total} dokumentów "
                    f"({', '.join(processed_names)}). Dane zostały zaksięgowane w rejestrze."
                )
                if timeout_names:
                    msg += f" (Limit czasu 90s przekroczony dla: {', '.join(timeout_names)})."
                if failed_names:
                    msg += f" (Nie udało się odczytać kwot z: {', '.join(failed_names)})."
                logger.info("Zakończono ekstrakcję AI dla %s (%s-%s): %s", profile.nazwa, rok, miesiac, msg)
                cls.set_task_status(
                    profile,
                    rok,
                    miesiac,
                    status="completed",
                    message=msg,
                    processed_files=processed_names,
                    current=total,
                    total=total,
                    percent=100,
                )
            else:
                all_failed = failed_names + timeout_names or [item["plik"] for item in unprocessed]
                names_str = ", ".join(all_failed)
                msg = (
                    f"Nie udało się automatycznie wyciągnąć danych z dokumentów ({names_str}). "
                    f"Kwoty nadal wynoszą 0,00 zł. Sprawdź jakość skanu lub konfigurację modelu AI."
                )
                logger.warning("Niepowodzenie ekstrakcji AI dla %s (%s-%s): %s", profile.nazwa, rok, miesiac, msg)
                cls.set_task_status(
                    profile,
                    rok,
                    miesiac,
                    status="error",
                    message=msg,
                    processed_files=[],
                    current=total,
                    total=total,
                    percent=100,
                )

        except Exception as e:
            logger.exception("Błąd podczas asynchronicznej ekstrakcji AI: %s", e)
            cls.set_task_status(
                profile,
                rok,
                miesiac,
                status="error",
                message=f"Błąd podczas wyciągania danych: {str(e)}",
            )

    @classmethod
    def start_ai_extraction(cls, profile: CompanyProfile, rok: str, miesiac: str) -> None:
        """Uruchamia zadanie asynchroniczne w bieżącej pętli zdarzeń asyncio."""
        current_status = cls.get_task_status(profile, rok, miesiac)
        if current_status.get("status") == "running":
            logger.info("Zadanie ekstrakcji dla %s (%s-%s) jest już uruchomione", profile.nazwa, rok, miesiac)
            return

        unprocessed = cls.get_unprocessed_invoices(profile, rok, miesiac)
        total_count = len(unprocessed)
        first_file = unprocessed[0]["plik"] if unprocessed else ""

        # Ustaw status 'running' natychmiast synchronicznie przed utworzeniem taska w tle,
        # dzięki czemu wywołanie get_task_status od razu zwraca stan trwającego przetwarzania
        cls.set_task_status(
            profile,
            rok,
            miesiac,
            status="running",
            message=f"Rozpoczynanie analizy AI dla {total_count} dokumentów..." if total_count > 0 else "Inicjalizacja analizy AI...",
            current=0,
            total=total_count,
            percent=0,
            current_file=first_file,
        )
        asyncio.create_task(cls.run_ai_extraction_job(profile, rok, miesiac))
