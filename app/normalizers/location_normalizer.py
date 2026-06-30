"""
location_normalizer.py — Location string → structured Location model.

Normalisation steps:
  1. Split the raw location string into city, state, country components.
  2. Identify and convert country name/alias → ISO-3166 Alpha-2 code.
  3. Return a Location Pydantic model with normalised fields.

Country lookup uses pycountry for comprehensive coverage (250+ countries).
"""
from __future__ import annotations

import re
from typing import Any, Optional

import pycountry

from app.models.candidate import Location
from app.utils.helpers import normalize_whitespace
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Common country aliases not always recognised by pycountry
_COUNTRY_OVERRIDES: dict[str, str] = {
    "usa": "US",
    "u.s.a": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "us": "US",
    "america": "US",
    "uk": "GB",
    "u.k": "GB",
    "u.k.": "GB",
    "great britain": "GB",
    "england": "GB",
    "uae": "AE",
    "u.a.e": "AE",
    "u.a.e.": "AE",
    "united arab emirates": "AE",
    "india": "IN",
    "china": "CN",
    "russia": "RU",
    "south korea": "KR",
    "korea": "KR",
    "taiwan": "TW",
    "hong kong": "HK",
    "new zealand": "NZ",
    "south africa": "ZA",
    "saudi arabia": "SA",
    "singapore": "SG",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
    "canada": "CA",
    "australia": "AU",
    "brazil": "BR",
    "mexico": "MX",
    "japan": "JP",
    "indonesia": "ID",
    "pakistan": "PK",
    "bangladesh": "BD",
    "nigeria": "NG",
    "egypt": "EG",
    "turkey": "TR",
    "iran": "IR",
    "thailand": "TH",
    "vietnam": "VN",
    "philippines": "PH",
    "malaysia": "MY",
    "netherlands": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "poland": "PL",
    "ukraine": "UA",
    "romania": "RO",
    "czech republic": "CZ",
    "czechia": "CZ",
    "hungary": "HU",
    "portugal": "PT",
    "greece": "GR",
    "israel": "IL",
    "colombia": "CO",
    "argentina": "AR",
    "chile": "CL",
    "peru": "PE",
    "venezuela": "VE",
    "ecuador": "EC",
    "kenya": "KE",
    "ghana": "GH",
    "ethiopia": "ET",
    "tanzania": "TZ",
    "uganda": "UG",
    "morocco": "MA",
    "algeria": "DZ",
    "tunisia": "TN",
}


class LocationNormalizer:
    """Normalises a raw location string into a structured Location model."""

    def normalize(self, raw: Any) -> Location:
        """Parse and normalise a location string, dictionary, or stringified dictionary.

        Args:
            raw: Raw location string (e.g. 'San Francisco, CA, United States'), or a dictionary.

        Returns:
            Location model with city, state, country (ISO α-2), and raw fields.
        """
        if not raw:
            return Location()

        if isinstance(raw, Location):
            return raw

        if isinstance(raw, dict):
            city = raw.get("city") or raw.get("town") or raw.get("locality")
            state = raw.get("state") or raw.get("province") or raw.get("region")
            country = raw.get("country")
            country_code = self._resolve_country(country) if country else None
            
            # Form clean raw string
            parts = [str(p) for p in [city, state, country] if p]
            cleaned_raw = ", ".join(parts)
            return Location(
                city=city,
                state=state,
                country=country_code,
                raw=cleaned_raw or raw.get("raw"),
            )

        if isinstance(raw, str):
            stripped = raw.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    import ast
                    parsed_dict = ast.literal_eval(stripped)
                    if isinstance(parsed_dict, dict):
                        return self.normalize(parsed_dict)
                except Exception:
                    pass

        cleaned = normalize_whitespace(str(raw)).strip()
        city: Optional[str] = None
        state: Optional[str] = None
        country_code: Optional[str] = None

        # Split on comma — most location strings use "City, State, Country"
        parts = [p.strip() for p in cleaned.split(",")]

        # Identify country from the last part
        if parts:
            country_code = self._resolve_country(parts[-1])
            if country_code:
                remaining = parts[:-1]
            else:
                remaining = parts

            if remaining:
                city = remaining[0] if remaining else None
            if len(remaining) >= 2:
                state = remaining[1]

        # Fallback: search all parts for a country name
        if not country_code:
            for part in parts:
                code = self._resolve_country(part)
                if code:
                    country_code = code
                    break

        result = Location(
            city=city,
            state=state,
            country=country_code,
            raw=cleaned,
        )
        logger.debug(
            "Location '%s' -> city='%s', state='%s', country='%s'",
            raw, city, state, country_code,
        )
        return result

    @staticmethod
    def _resolve_country(text: str) -> Optional[str]:
        """Convert a country name or code to ISO-3166 Alpha-2.

        Args:
            text: Country name, common alias, or existing Alpha-2 code.

        Returns:
            Two-letter ISO code (e.g. 'US'), or None if not recognised.
        """
        if not text:
            return None

        cleaned = text.strip()

        # Already an Alpha-2 code?
        if re.fullmatch(r"[A-Za-z]{2}", cleaned):
            upper = cleaned.upper()
            country = pycountry.countries.get(alpha_2=upper)
            if country:
                return upper

        # Check override table first (case-insensitive)
        lower = cleaned.lower()
        override = _COUNTRY_OVERRIDES.get(lower)
        if override:
            return override

        # Try pycountry lookup by name
        try:
            country = pycountry.countries.lookup(cleaned)
            return country.alpha_2
        except LookupError:
            pass

        # Try pycountry fuzzy search (more expensive)
        try:
            results = pycountry.countries.search_fuzzy(cleaned)
            if results:
                return results[0].alpha_2
        except (LookupError, Exception):
            pass

        return None


# Module-level singleton
_default_normalizer = LocationNormalizer()


def normalize_location(raw: Any) -> Location:
    """Convenience function: normalise a location string or dict.

    Args:
        raw: Raw location string, dict, or stringified dict.

    Returns:
        Location model.
    """
    return _default_normalizer.normalize(raw)


def resolve_country_code(text: str) -> Optional[str]:
    """Convenience function: resolve a country name to ISO Alpha-2.

    Args:
        text: Country name or alias.

    Returns:
        Two-letter ISO code, or None.
    """
    return LocationNormalizer._resolve_country(text)
