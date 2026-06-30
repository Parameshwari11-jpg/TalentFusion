"""
logger.py — Structured application logger.

Provides a single factory function ``get_logger`` that returns a
consistently configured ``logging.Logger``.  All modules use this
instead of calling ``logging.getLogger`` directly, ensuring uniform
formatting across the entire application.

Log levels:
    DEBUG   — low-level internals (normaliser transformations, etc.)
    INFO    — high-level pipeline steps (parser started, merge complete)
    WARNING — non-fatal problems (missing field, fuzzy match used)
    ERROR   — caught exceptions that degraded gracefully
    CRITICAL— would only be used if the entire pipeline cannot proceed
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Default format — human-readable and grep-friendly
# ---------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Module-level flag to ensure root logger is configured only once.
_root_configured: bool = False


def _configure_root(
    level: int,
    log_file: Optional[Path],
) -> None:
    """Configure the root logger exactly once (idempotent)."""
    global _root_configured
    if _root_configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    # Quiet down verbose third-party loggers
    for logger_name in ["pdfminer", "urllib3", "PIL", "matplotlib"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    # File handler (optional)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)

    _root_configured = True


def get_logger(
    name: str,
    level: int = logging.DEBUG,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Return a named logger, ensuring the root is configured.

    Usage::

        from app.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Parser started")

    Args:
        name:     Logger name, conventionally ``__name__``.
        level:    Log level (default: DEBUG).
        log_file: Optional path to a log file.  If provided, log output
                  is written to both stdout and the file.

    Returns:
        A configured ``logging.Logger`` instance.
    """
    _configure_root(level, log_file)
    return logging.getLogger(name)
