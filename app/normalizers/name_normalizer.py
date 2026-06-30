"""
name_normalizer.py — Candidate name normalisation.

Rules:
  - Strip leading/trailing whitespace.
  - Collapse internal whitespace.
  - Apply Title Case, preserving embedded capital letters (e.g. 'McDonald').
  - Remove non-alphabetic characters that are clearly noise (e.g. digits).
  - Never crash — returns the cleaned input on any failure.
"""
from __future__ import annotations

import re

from app.utils.helpers import normalize_whitespace, to_title_case
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Characters to strip from name strings (common OCR noise)
_NOISE_RE = re.compile(r"[^\w\s'\-\.]", re.UNICODE)
# Digits in a name are almost always OCR errors
_DIGIT_RE = re.compile(r"\d")


def normalize_name(raw: str) -> tuple[str, bool]:
    """Normalise a candidate name string.

    Args:
        raw: Raw name string from any source.

    Returns:
        Tuple of (normalised_name, is_valid):
          - normalised_name: Cleaned, title-cased name.
          - is_valid: False if the result appears to be noise (too short,
                      too many digits, etc.).
    """
    if not raw or not raw.strip():
        return raw, False

    try:
        # Remove obvious noise characters
        cleaned = _NOISE_RE.sub(" ", raw)
        cleaned = normalize_whitespace(cleaned)

        # Validation heuristics
        if _DIGIT_RE.search(cleaned):
            logger.debug("Name '%s' contains digits — may be an OCR error.", raw)

        if len(cleaned) < 2:
            return cleaned, False

        # Title case
        result = to_title_case(cleaned)
        is_valid = (
            2 <= len(result) <= 100
            and not _DIGIT_RE.search(result)
            and len(result.split()) <= 7  # Very long names are suspicious
        )

        logger.debug("Name '%s' -> '%s' (valid=%s)", raw, result, is_valid)
        return result, is_valid

    except Exception as exc:
        logger.error("Name normalisation failed for '%s': %s", raw, exc)
        return raw, False
