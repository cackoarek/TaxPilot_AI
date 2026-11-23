"""
src/logging_config.py
Centralna konfiguracja rejestrowania zdarzeń (logging) dla aplikacji TaxPilot AI.
Loguje zdarzenia do konsoli oraz do trwałego pliku taxpilot.log w katalogu projektu.
"""

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import BASE_DIR

LOG_FILE = BASE_DIR / "taxpilot.log"
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class SecretMaskingFilter(logging.Filter):
    """
    Filtr loggingu maskujący wrażliwe dane (klucze API, tokeny, hasła) w strumieniach logów (SEC-21).
    Chroni przed przypadkowym wyciekiem do taxpilot.log i stdout/stderr.
    """

    PATTERNS = [
        # Google API keys: AIzaSy... (39+ znaków)
        (re.compile(r"AIza[0-9A-Za-z-_]{35,}"), "AIza...[MASKED]"),
        # Anthropic Claude API keys: sk-ant-... (przed ogólnym sk-)
        (re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"), "sk-ant-...[MASKED]"),
        # OpenAI API keys: sk-...
        (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "sk-...[MASKED]"),
        # Bearer tokens w nagłówkach
        (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{16,}", re.IGNORECASE), r"\1[MASKED_TOKEN]"),
        # Tokeny KSeF w JSON lub XML
        (re.compile(r'("token"\s*:\s*")[^"]+(")', re.IGNORECASE), r'\1[MASKED_TOKEN]\2'),
        (re.compile(r'("SessionToken"\s*:\s*")[^"]+(")', re.IGNORECASE), r'\1[MASKED_KSEF_TOKEN]\2'),
        (re.compile(r"(<SessionToken>)[^<]+(</SessionToken>)", re.IGNORECASE), r"\1[MASKED_KSEF_TOKEN]\2"),
        # Hasła w JSON
        (re.compile(r'("password"\s*:\s*")[^"]+(")', re.IGNORECASE), r'\1[MASKED_PASSWORD]\2'),
    ]

    @classmethod
    def mask_text(cls, text: str) -> str:
        for pattern, replacement in cls.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_text(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(self.mask_text(str(a)) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {
                    k: (self.mask_text(str(v)) if isinstance(v, str) else v) for k, v in record.args.items()
                }
        return True


def setup_logging(level=logging.INFO) -> logging.Logger:
    """
    Inicjalizuje globalne logowanie dla aplikacji TaxPilot AI.
    Zapisuje wszystkie logi (w tym pełne stacktrace'y wyjątków) do:
    - pliku taxpilot.log z rotacją (maks. 10MB x 5 kopii)
    - konsoli (stdout/stderr)
    Automatycznie maskuje sekrety za pomocą SecretMaskingFilter (SEC-21).
    """
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    mask_filter = SecretMaskingFilter()
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addFilter(mask_filter)

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
        file_handler.addFilter(mask_filter)
        root_logger.addHandler(file_handler)

    # 2. Obsługa konsoli (stdout)
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers
    )
    if not has_stream:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(mask_filter)
        root_logger.addHandler(stream_handler)

    # Synchronizacja logerów Uvicorn i FastAPI
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        sub_logger = logging.getLogger(logger_name)
        sub_logger.setLevel(level)
        sub_logger.addFilter(mask_filter)
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
            file_h.addFilter(mask_filter)
            sub_logger.addHandler(file_h)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Zwraca nazwany logger z aktywną konfiguracją."""
    return logging.getLogger(name)
