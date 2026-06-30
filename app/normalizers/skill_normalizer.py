"""
skill_normalizer.py — Canonical skill name resolution.

Two-stage lookup:
  1. Exact alias match (case-insensitive) against skill_aliases.json.
  2. RapidFuzz partial-ratio fuzzy matching against all alias strings,
     with a configurable threshold (default SKILL_FUZZY_THRESHOLD = 82).

If both stages fail, the original skill name is returned as-is with
a note that it could not be canonicalised.

The canonicaliser is deterministic: same input → same output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rapidfuzz import process, fuzz

from app.utils.helpers import load_json_file, normalize_whitespace
from app.utils.logger import get_logger
from config.settings import CONFIG_DIR, SKILL_FUZZY_THRESHOLD

logger = get_logger(__name__)


class SkillNormalizer:
    """Resolves raw skill strings to canonical skill names.

    Args:
        alias_map_path: Path to skill_aliases.json.
                        Defaults to config/skill_aliases.json.
        fuzzy_threshold: Minimum RapidFuzz token-sort ratio score (0–100)
                         for a fuzzy match to be accepted.
    """

    def __init__(
        self,
        alias_map_path: Optional[Path] = None,
        fuzzy_threshold: int = SKILL_FUZZY_THRESHOLD,
    ) -> None:
        path = alias_map_path or (CONFIG_DIR / "skill_aliases.json")
        raw_map: dict[str, list[str]] = load_json_file(path)

        # Build lookup structures
        # canonical_name (lower) → canonical_name (original case)
        self._canonical_lookup: dict[str, str] = {}
        # alias (lower) → canonical_name (original case)
        self._alias_lookup: dict[str, str] = {}
        # All alias strings for fuzzy matching
        self._all_aliases: list[str] = []

        for canonical, aliases in raw_map.items():
            if canonical.startswith("_"):
                continue  # Skip comment fields
            lower_canonical = canonical.lower()
            self._canonical_lookup[lower_canonical] = canonical
            self._alias_lookup[lower_canonical] = canonical

            for alias in aliases:
                lower_alias = alias.lower()
                self._alias_lookup[lower_alias] = canonical
                self._all_aliases.append(alias)

        self._fuzzy_threshold = fuzzy_threshold
        logger.debug(
            "SkillNormalizer loaded %d canonical skills, %d aliases.",
            len(self._canonical_lookup),
            len(self._all_aliases),
        )

    def normalize(self, raw_skill: str) -> tuple[str, bool, str]:
        """Resolve a raw skill string to its canonical name.

        Args:
            raw_skill: Raw skill string (e.g. 'JS', 'java script').

        Returns:
            Tuple of (canonical_name, was_canonicalised, match_method):
              - canonical_name: The resolved canonical name, or raw_skill.
              - was_canonicalised: True if a canonical mapping was found.
              - match_method: 'exact', 'fuzzy', or 'passthrough'.
        """
        if not raw_skill or not raw_skill.strip():
            return raw_skill, False, "passthrough"

        cleaned = normalize_whitespace(raw_skill).strip(".,;:")
        lower = cleaned.lower()

        # Stage 1: Exact alias lookup
        canonical = self._alias_lookup.get(lower)
        if canonical:
            logger.debug("Skill '%s' -> '%s' (exact match)", raw_skill, canonical)
            return canonical, True, "exact"

        # Stage 2: Fuzzy matching
        canonical = self._fuzzy_match(cleaned)
        if canonical:
            logger.debug(
                "Skill '%s' -> '%s' (fuzzy match, threshold=%d)",
                raw_skill, canonical, self._fuzzy_threshold,
            )
            return canonical, True, "fuzzy"

        # Stage 3: Passthrough — return cleaned version
        logger.debug("Skill '%s' could not be canonicalised — keeping as-is.", raw_skill)
        return cleaned, False, "passthrough"

    def _fuzzy_match(self, skill: str) -> Optional[str]:
        """Find the best-matching canonical alias using RapidFuzz.

        Uses token_sort_ratio which handles word-order variations.

        Args:
            skill: Cleaned skill string.

        Returns:
            Canonical name if a match meets the threshold, else None.
        """
        if not self._all_aliases:
            return None
        result = process.extractOne(
            skill,
            self._all_aliases,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=self._fuzzy_threshold,
        )
        if result is None:
            return None
        best_alias, score, _ = result
        return self._alias_lookup.get(best_alias.lower())

    def normalize_list(self, raw_skills: list[str]) -> list[tuple[str, bool, str]]:
        """Normalise a list of skill strings.

        Args:
            raw_skills: List of raw skill strings.

        Returns:
            List of (canonical_name, was_canonicalised, match_method) tuples.
        """
        return [self.normalize(s) for s in raw_skills if s and s.strip()]


# Module-level singleton (constructed once, reused)
_default_normalizer: Optional[SkillNormalizer] = None


def _get_normalizer() -> SkillNormalizer:
    global _default_normalizer
    if _default_normalizer is None:
        _default_normalizer = SkillNormalizer()
    return _default_normalizer


def normalize_skill(raw: str) -> tuple[str, bool, str]:
    """Convenience function: normalise a single skill string.

    Args:
        raw: Raw skill string.

    Returns:
        Tuple of (canonical_name, was_canonicalised, match_method).
    """
    return _get_normalizer().normalize(raw)
