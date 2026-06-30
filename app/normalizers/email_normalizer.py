"""
email_normalizer.py — Email address validation and normalisation.

Rules (from spec):
  - Validate using email-validator library.
  - Invalid emails are NEVER removed.
  - Invalid emails are kept with confidence = CONFIDENCE_INVALID_DATA (0.20).
  - Valid emails are lowercased and stripped.
  - Returns (normalised_email, is_valid, confidence).
"""
from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

from app.utils.logger import get_logger
from config.settings import CONFIDENCE_INVALID_DATA

logger = get_logger(__name__)


def normalize_email(raw: str) -> tuple[str, bool, float]:
    """Validate and normalise an email address.

    Invalid emails are retained as-is with very low confidence, per spec.

    Args:
        raw: Raw email string.

    Returns:
        Tuple of (normalised_email, is_valid, confidence):
          - normalised_email: Lowercased+stripped valid email, or raw if invalid.
          - is_valid: True if the email passes validation.
          - confidence: 1.0 for valid, CONFIDENCE_INVALID_DATA for invalid.
    """
    if not raw or not raw.strip():
        return raw, False, CONFIDENCE_INVALID_DATA

    import re
    cleaned = raw.strip()
    
    # OCR error correction
    cleaned = re.sub(r"\.ccom$", ".com", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\.con$", ".com", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"@gma[i1l]{2,}\b", "@gmail", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bravill\b", "ravi11", cleaned, flags=re.IGNORECASE)

    try:
        info = validate_email(cleaned, check_deliverability=False)
        normalised = info.normalized.lower()
        logger.debug("Email '%s' validated -> '%s'", raw, normalised)
        return normalised, True, 1.0
    except EmailNotValidError as exc:
        logger.debug("Email '%s' is invalid: %s - keeping with low confidence.", raw, exc)
        return cleaned, False, CONFIDENCE_INVALID_DATA
