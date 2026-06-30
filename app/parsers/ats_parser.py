"""
ats_parser.py — ATS JSON → ParsedSource

Responsibilities:
  1. Load the ATS field-alias map from config/ats_field_map.json.
  2. Traverse the raw ATS dict using a configurable alias lookup so that
     ANY field name convention (camelCase, snake_case, vendor-specific) is
     mapped to a canonical key — without touching code.
  3. Wrap each extracted value in a RawField tagged with source=ATS and
     method='ats_parser'.
  4. Return a ParsedSource.  Never raise — all errors are logged and
     collected in ParsedSource.parse_errors.

Design decisions:
  - Field alias resolution is purely data-driven (ats_field_map.json).
  - Sub-objects (experience, education) are parsed into typed dicts.
  - No normalisation happens here — the normaliser layer handles that.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.models.candidate import (
    ParsedSource,
    RawField,
)
from app.models.confidence import SourceType, get_base_confidence
from app.utils.helpers import is_empty, load_json_file, normalize_whitespace
from app.utils.logger import get_logger
from config.settings import (
    CONFIG_DIR,
    METHOD_ATS_PARSER,
    SOURCE_ATS,
)

logger = get_logger(__name__)

# Confidence for any value sourced from ATS
_ATS_CONFIDENCE: float = get_base_confidence(SourceType.ATS)


class ATSParser:
    """Parses a raw ATS JSON payload into a ParsedSource.

    The parser is stateless once constructed; the field-map is loaded
    once at construction time and cached for the lifetime of the object.

    Args:
        field_map_path: Path to the ATS field-alias JSON config.
                        Defaults to config/ats_field_map.json.
    """

    def __init__(self, field_map_path: Optional[Path] = None) -> None:
        path = field_map_path or (CONFIG_DIR / "ats_field_map.json")
        self._field_map: dict[str, Any] = load_json_file(path)
        logger.debug("ATSParser initialised with field map from %s", path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, raw: dict[str, Any]) -> ParsedSource:
        """Parse a raw ATS dict into a ParsedSource.

        Args:
            raw: The ATS JSON payload as a Python dict.

        Returns:
            ParsedSource with extracted fields and any non-fatal errors.
        """
        errors: list[str] = []
        fields: dict[str, Any] = {}
        list_fields: dict[str, list[Any]] = {}

        try:
            # --- Scalar fields ---
            for canonical, raw_field in self._extract_scalar_fields(raw, errors):
                fields[canonical] = raw_field

            # --- List fields: skills, emails, phones ---
            for canonical, raw_field_list in self._extract_list_fields(raw, errors):
                list_fields[canonical] = raw_field_list

            # --- Structured lists: experience, education ---
            exp_list = self._extract_experience(raw, errors)
            if exp_list:
                list_fields["experience"] = exp_list

            edu_list = self._extract_education(raw, errors)
            if edu_list:
                list_fields["education"] = edu_list

            # --- Links ---
            links_field = self._extract_links(raw, errors)
            if links_field is not None:
                fields["links"] = links_field

        except Exception as exc:  # pragma: no cover
            msg = f"Unexpected error in ATSParser.parse: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        logger.info(
            "ATSParser complete — %d scalar fields, %d list fields, %d errors",
            len(fields),
            len(list_fields),
            len(errors),
        )
        return ParsedSource(
            source_type=SourceType.ATS,
            fields=fields,
            list_fields=list_fields,
            parse_errors=errors,
            available=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_key_recursive(self, data: Any, key: str) -> Optional[Any]:
        """Recursively search for a key in a nested dictionary/list structure."""
        if isinstance(data, dict):
            if key in data:
                return data[key]
            for v in data.values():
                res = self._find_key_recursive(v, key)
                if res is not None:
                    return res
        elif isinstance(data, list):
            for item in data:
                res = self._find_key_recursive(item, key)
                if res is not None:
                    return res
        return None

    def _resolve(self, raw: dict[str, Any], canonical: str) -> Optional[Any]:
        """Find the value in ``raw`` corresponding to a canonical field name.

        Iterates through the alias list for ``canonical`` and returns the
        first non-empty match (first checking root, then recursively).

        Args:
            raw:       The raw ATS dict.
            canonical: Canonical field name (e.g. 'full_name').

        Returns:
            The raw value, or None if not found.
        """
        aliases: list[str] = (
            self._field_map.get("name_mappings", {}).get(canonical, [canonical])
        )
        for alias in aliases:
            value = raw.get(alias)
            if not is_empty(value):
                logger.debug("Resolved '%s' via alias '%s' at root", canonical, alias)
                return value
            
            value = self._find_key_recursive(raw, alias)
            if not is_empty(value):
                logger.debug("Resolved '%s' via alias '%s' recursively", canonical, alias)
                return value
        return None

    def _make_raw_field(self, value: Any, raw: Any = None) -> RawField:
        """Wrap a value in a RawField tagged for ATS."""
        return RawField(
            value=value,
            source=SourceType.ATS,
            confidence=_ATS_CONFIDENCE,
            method=METHOD_ATS_PARSER,
            raw=raw if raw is not None else value,
        )

    def _extract_scalar_fields(
        self, raw: dict[str, Any], errors: list[str]
    ) -> list[tuple[str, RawField]]:
        """Extract all scalar (non-list, non-structured) canonical fields."""
        scalar_canonicals = [
            "full_name",
            "headline",
            "years_experience",
            "location",
        ]
        result: list[tuple[str, RawField]] = []
        for canonical in scalar_canonicals:
            try:
                value = self._resolve(raw, canonical)
                if value is not None:
                    result.append((canonical, self._make_raw_field(value)))
            except Exception as exc:
                msg = f"Error extracting scalar field '{canonical}': {exc}"
                logger.warning(msg)
                errors.append(msg)
        return result

    def _extract_list_fields(
        self, raw: dict[str, Any], errors: list[str]
    ) -> list[tuple[str, list[RawField]]]:
        """Extract list fields: skills, emails, phones."""
        list_canonicals = ["skills", "emails", "phones"]
        result: list[tuple[str, list[RawField]]] = []

        for canonical in list_canonicals:
            try:
                value = self._resolve(raw, canonical)
                if value is None:
                    continue
                # Normalise to a list
                if isinstance(value, str):
                    # comma-separated string  e.g. "Python, JS, React"
                    items = [v.strip() for v in value.split(",") if v.strip()]
                elif isinstance(value, list):
                    items = [str(v).strip() for v in value if not is_empty(v)]
                else:
                    items = [str(value).strip()]

                raw_fields = [self._make_raw_field(item, raw=item) for item in items]
                if raw_fields:
                    result.append((canonical, raw_fields))
            except Exception as exc:
                msg = f"Error extracting list field '{canonical}': {exc}"
                logger.warning(msg)
                errors.append(msg)
        return result

    def _extract_experience(
        self, raw: dict[str, Any], errors: list[str]
    ) -> list[RawField]:
        """Extract the work-experience list as RawField[dict] entries."""
        value = self._resolve(raw, "experience")
        if is_empty(value):
            return []
        if not isinstance(value, list):
            errors.append(f"'experience' field is not a list: {type(value)}")
            return []

        sub_map: dict[str, list[str]] = (
            self._field_map.get("experience_sub_fields", {})
        )
        result: list[RawField] = []
        for i, entry in enumerate(value):
            if not isinstance(entry, dict):
                errors.append(f"Experience entry {i} is not a dict, skipping.")
                continue
            try:
                normalised = self._map_sub_fields(entry, sub_map)
                result.append(self._make_raw_field(normalised, raw=entry))
            except Exception as exc:
                msg = f"Error parsing experience entry {i}: {exc}"
                logger.warning(msg)
                errors.append(msg)
        return result

    def _extract_education(
        self, raw: dict[str, Any], errors: list[str]
    ) -> list[RawField]:
        """Extract the education list as RawField[dict] entries."""
        value = self._resolve(raw, "education")
        if is_empty(value):
            return []
        if not isinstance(value, list):
            errors.append(f"'education' field is not a list: {type(value)}")
            return []

        sub_map: dict[str, list[str]] = (
            self._field_map.get("education_sub_fields", {})
        )
        result: list[RawField] = []
        for i, entry in enumerate(value):
            if not isinstance(entry, dict):
                errors.append(f"Education entry {i} is not a dict, skipping.")
                continue
            try:
                normalised = self._map_sub_fields(entry, sub_map)
                result.append(self._make_raw_field(normalised, raw=entry))
            except Exception as exc:
                msg = f"Error parsing education entry {i}: {exc}"
                logger.warning(msg)
                errors.append(msg)
        return result

    def _extract_links(
        self, raw: dict[str, Any], errors: list[str]
    ) -> Optional[RawField]:
        """Build a links dict from linkedin, github, and portfolio fields."""
        links: dict[str, str] = {}
        for link_key in ("linkedin", "github", "portfolio"):
            value = self._resolve(raw, link_key)
            if not is_empty(value):
                links[link_key] = str(value).strip()

        # Also check a top-level 'links' dict
        raw_links = self._resolve(raw, "links")
        if isinstance(raw_links, dict):
            for k, v in raw_links.items():
                if k in ("linkedin", "github", "portfolio") and not is_empty(v):
                    links.setdefault(k, str(v).strip())

        if not links:
            return None
        return self._make_raw_field(links, raw=raw_links or links)

    @staticmethod
    def _map_sub_fields(
        entry: dict[str, Any], sub_map: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Map sub-fields of experience/education to canonical keys.

        Args:
            entry:   A single dict entry from the ATS list.
            sub_map: Mapping of canonical sub-field → alias list.

        Returns:
            Dict with canonical keys.
        """
        result: dict[str, Any] = {}
        for canonical, aliases in sub_map.items():
            for alias in aliases:
                value = entry.get(alias)
                if not is_empty(value):
                    result[canonical] = value
                    break
        # Preserve any fields not in the sub_map
        for k, v in entry.items():
            if k not in {alias for aliases in sub_map.values() for alias in aliases}:
                result.setdefault(k, v)
        return result


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def parse_ats(raw: dict[str, Any]) -> ParsedSource:
    """Convenience function: parse an ATS dict without instantiating the class.

    Args:
        raw: ATS JSON payload as a dict.

    Returns:
        ParsedSource.
    """
    return ATSParser().parse(raw)
