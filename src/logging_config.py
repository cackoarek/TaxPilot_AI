"""
src/logging_config.py
Centralna konfiguracja rejestrowania zdarzeń (logging) dla aplikacji TaxPilot AI.
Loguje zdarzenia do konsoli oraz do trwałego pliku taxpilot.log w katalogu projektu.
"""
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import BASE_DIR

LOG_FILE = BASE_DIR / "taxpilot.log"
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level=logging.INFO) -> logging.Logger:
    """
    Inicjalizuje globalne logowanie dla aplikacji TaxPilot AI.
    Zapisuje wszystkie logi (w tym pełne stacktrace'y wyjątków) do:
    - pliku taxpilot.log z rotacją (maks. 10MB x 5 kopii)
    - konsoli (stdout/stderr)
    """
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 1. Obsługa pliku taxpilot.log
    has_file = any(
        isinstance(h, RotatingFileHandler) and Path(getattr(h, "baseFilename", "")).resolve() == LOG_FILE.resolve()
        for h in root_logger.handlers
    )
    if not has_file:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # 2. Obsługa konsoli (stdout)
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in root_logger.handlers
    )
    if not has_stream:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    # Synchronizacja logerów Uvicorn i FastAPI
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(level)
        # Jeśli uvicorn nie propaguje, dodaj file handler
        if not any(isinstance(h, RotatingFileHandler) for h in sub_logger.handlers):
            file_h = RotatingFileHandler(
                LOG_FILE,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_h.setLevel(level)
            file_h.setFormatter(formatter)
            sub_logger.addHandler(file_h)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Zwraca nazwany logger z aktywną konfiguracją."""
    return logging.getLogger(name)
