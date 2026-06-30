"""
phone_normalizer.py — Phone number normalisation to E.164 format.

Rules:
  - If a country code can be inferred (from the number itself, from the
    candidate's location, or from a default), normalise to E.164.
  - If the country is completely unknown and the number is ambiguous,
    return the number as-is (cleaned of excess whitespace).
  - Invalid numbers are kept as-is with CONFIDENCE_INVALID_DATA.
  - Never removes a phone number — always returns *something*.
"""
from __future__ import annotations

from typing import Optional

import phonenumbers
from phonenumbers import NumberParseException

from app.utils.logger import get_logger
from config.settings import CONFIDENCE_INVALID_DATA

logger = get_logger(__name__)

# Default country to try when the number has no explicit country code.
# E.164 requires a country hint for local numbers.
_DEFAULT_REGION = "US"


class PhoneNormalizer:
    """Normalises phone numbers to E.164 format.

    Args:
        default_region: BCP-47 region code used when no country hint is
                        available (e.g. 'US', 'IN').  Defaults to 'US'.
    """

    def __init__(self, default_region: str = _DEFAULT_REGION) -> None:
        self._default_region = default_region

    def normalize(
        self,
        raw_phone: str,
        country_hint: Optional[str] = None,
    ) -> tuple[str, float]:
        """Normalise a phone string to E.164.

        Args:
            raw_phone:    Raw phone string from any source.
            country_hint: ISO-3166 Alpha-2 country code (e.g. 'IN').
                          When provided, used as the region hint.

        Returns:
            Tuple of (normalised_phone, confidence).
            - If successfully normalised: (E.164 string, original confidence)
            - If invalid: (cleaned raw string, CONFIDENCE_INVALID_DATA)
        """
        if not raw_phone or not raw_phone.strip():
            return raw_phone, CONFIDENCE_INVALID_DATA

        cleaned = raw_phone.strip()
        region = country_hint or self._default_region

        # Try parsing with the region hint
        result, confidence = self._try_parse(cleaned, region)
        if result:
            return result, 1.0  # Parsed successfully; confidence = 1.0 for the normalisation itself

        # Try without a region hint (works for international numbers with '+')
        result, confidence = self._try_parse(cleaned, None)
        if result:
            return result, 1.0

        # Could not parse -> return as-is with low confidence
        logger.debug("Could not normalise phone '%s' - keeping as-is.", cleaned)
        return cleaned, CONFIDENCE_INVALID_DATA

    @staticmethod
    def _try_parse(
        phone: str,
        region: Optional[str],
    ) -> tuple[Optional[str], float]:
        """Attempt to parse and format a phone number.

        Args:
            phone:  Raw phone string.
            region: Optional BCP-47 region hint.

        Returns:
            Tuple of (E.164 string, confidence) or (None, 0.0) on failure.
        """
        try:
            parsed = phonenumbers.parse(phone, region)
            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                return e164, 1.0
        except NumberParseException:
            pass
        return None, 0.0


# Module-level convenience
_default_normalizer = PhoneNormalizer()


def normalize_phone(
    raw: str,
    country_hint: Optional[str] = None,
) -> tuple[str, float]:
    """Normalise a phone number to E.164 using a default normalizer.

    Args:
        raw:          Raw phone string.
        country_hint: ISO-3166 Alpha-2 country code hint.

    Returns:
        Tuple of (normalised_phone, confidence).
    """
    return _default_normalizer.normalize(raw, country_hint)
