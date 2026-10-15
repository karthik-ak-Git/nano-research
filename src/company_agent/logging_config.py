"""Logging configuration with secret redaction and structured formatting."""

import logging
import re
import sys
from typing import Any

# Sensitive patterns to scrub from all logs
_SECRET_PATTERNS = [
    re.compile(r"(AIza[0-9A-Za-z-_]{35})", re.IGNORECASE),
    re.compile(r"(bearer\s+)([a-zA-Z0-9_\-\.]{20,})", re.IGNORECASE),
    re.compile(r"(x-api-key['\"]?:\s*['\"]?)([a-zA-Z0-9_\-\.]{10,})", re.IGNORECASE),
    re.compile(r"(api[-_]?key['\"]?\s*[:=]\s*['\"]?)([a-zA-Z0-9_\-\.]{10,})", re.IGNORECASE),
]


class SecretRedactingFormatter(logging.Formatter):
    """Custom logging formatter that redacts detected API keys and secrets."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        redacted = original
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1***REDACTED***", redacted)
        return redacted


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configures application-wide logging with secret masking."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger("company_agent")
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers if reconfigured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(numeric_level)
        formatter = SecretRedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Silence verbose 3rd party logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logger


logger = configure_logging()
