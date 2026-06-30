"""
date_normalizer.py — Date string normalisation to YYYY-MM format.

Handles:
  - "Jan 2024", "January 2024"        → "2024-01"
  - "01/2024", "01-2024"              → "2024-01"
  - "2024-01", "2024/01"              → "2024-01" (already correct)
  - "Present", "Current", "Now"       → "Present"
  - Plain year "2024"                 → "2024-01" (assume January)
  - Full ISO dates "2024-01-15"       → "2024-01" (truncate to month)
  - Ambiguous inputs                  → logged warning, returned as-is

The normaliser is deterministic: the same input always produces the
same output.  It uses dateparser as the primary parser and falls back
to regex patterns for performance and reliability.
"""
from __future__ import annotations

import re
from typing import Optional

import dateparser

from app.utils.logger import get_logger
from config.settings import DATE_OUTPUT_FORMAT

logger = get_logger(__name__)

# Strings that mean "still employed here" / "current"
_PRESENT_ALIASES: frozenset[str] = frozenset({
    "present", "current", "now", "ongoing", "till date",
    "till now", "to date", "today", "—", "-", "–",
})

# Regex patterns for common date formats (tried before dateparser for speed)
_REGEX_PATTERNS: list[tuple[re.Pattern, str]] = [
    # YYYY-MM or YYYY/MM
    (re.compile(r"^(\d{4})[-/](\d{1,2})$"), "{year}-{month}"),
    # MM/YYYY or MM-YYYY
    (re.compile(r"^(\d{1,2})[-/](\d{4})$"), "{year}-{month}"),
    # Full ISO: YYYY-MM-DD
    (re.compile(r"^(\d{4})-(\d{2})-\d{2}$"), "{year}-{month}"),
    # Plain year
    (re.compile(r"^(\d{4})$"), "{year}-01"),
]


def normalize_date(raw: str) -> tuple[str, bool]:
    """Normalise a date string to YYYY-MM format.

    Args:
        raw: Input date string in any common format.

    Returns:
        Tuple of (normalised_date, is_valid):
          - normalised_date: "YYYY-MM", "Present", or the original string.
          - is_valid: True if normalisation succeeded.
    """
    if not raw or not raw.strip():
        return raw, False

    cleaned = raw.strip()

    # Check for "Present" aliases first
    if cleaned.lower() in _PRESENT_ALIASES:
        return "Present", True

    # Try fast regex patterns
    result = _try_regex_patterns(cleaned)
    if result:
        return result, True

    # Try dateparser (handles "Jan 2024", "January 2024", etc.)
    result = _try_dateparser(cleaned)
    if result:
        return result, True

    # Could not parse
    logger.warning("Could not normalise date: '%s' - keeping as-is.", cleaned)
    return cleaned, False


def _try_regex_patterns(text: str) -> Optional[str]:
    """Try fast regex-based parsing before invoking dateparser."""
    for pattern, template in _REGEX_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            # Determine which group is year and which is month
            g0, g1 = groups
            if len(g0) == 4:          # YYYY-MM
                year, month = g0, g1.zfill(2)
            else:                      # MM-YYYY
                month, year = g0.zfill(2), g1
        else:
            year = groups[0]
            month = "01"
        try:
            year_int = int(year)
            month_int = int(month)
            if 1900 <= year_int <= 2100 and 1 <= month_int <= 12:
                return f"{year_int:04d}-{month_int:02d}"
        except (ValueError, IndexError):
            continue
    return None


def _try_dateparser(text: str) -> Optional[str]:
    """Use dateparser as a fallback for complex date strings."""
    try:
        settings = {
            "PREFER_DAY_OF_MONTH": "first",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_LOCALE_DATE_ORDER": True,
        }
        parsed = dateparser.parse(text, settings=settings)
        if parsed:
            return parsed.strftime(DATE_OUTPUT_FORMAT)
    except Exception as exc:
        logger.debug("dateparser failed for '%s': %s", text, exc)
    return None
