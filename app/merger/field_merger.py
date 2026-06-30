"""
field_merger.py — Single-field conflict resolution.

For each canonical scalar field, this module:
  1. Collects all RawField values from all ParsedSources.
  2. Groups values by normalised content (deduplication).
  3. Identifies agreeing sources.
  4. Applies the agreement-bonus confidence model.
  5. Picks the winning value (highest confidence wins; ties broken by
     source priority: ATS > Resume > GitHub).
  6. Records provenance for all candidates.
"""
from __future__ import annotations

from typing import Any, Optional

from app.models.candidate import RawField
from app.models.confidence import ConfidenceScore, SourceType, get_base_confidence
from app.models.provenance import ProvenanceRecord
from app.confidence.confidence_engine import ConfidenceEngine
from app.provenance.provenance_tracker import ProvenanceTracker
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Source priority for tie-breaking (higher = preferred)
_SOURCE_PRIORITY: dict[SourceType, int] = {
    SourceType.ATS: 3,
    SourceType.RESUME: 2,
    SourceType.GITHUB: 1,
}


class FieldMerger:
    """Resolves conflicts for a single scalar field across multiple sources.

    Args:
        confidence_engine:  For computing agreement-bonus scores.
        provenance_tracker: For recording all merge decisions.
    """

    def __init__(
        self,
        confidence_engine: ConfidenceEngine,
        provenance_tracker: ProvenanceTracker,
    ) -> None:
        self._confidence = confidence_engine
        self._provenance = provenance_tracker

    def merge(
        self,
        field: str,
        candidates: list[RawField],
        normalise_fn=None,
    ) -> tuple[Optional[Any], ConfidenceScore]:
        """Merge multiple RawField values for a single scalar field.

        Args:
            field:        Canonical field name (e.g. 'full_name').
            candidates:   All RawField values from all sources.
            normalise_fn: Optional callable(raw_value) → normalised_value.
                          Used to group semantically-equivalent values.

        Returns:
            Tuple of (winning_value, ConfidenceScore).
            winning_value is None if no candidates were provided.
        """
        if not candidates:
            return None, ConfidenceScore(field=field, score=0.0)

        # --- Step 1: Normalise values for grouping ---
        normed: list[tuple[RawField, Any]] = []
        for rf in candidates:
            try:
                nv = normalise_fn(rf.value) if normalise_fn else rf.value
            except Exception as exc:
                logger.warning("normalise_fn failed for field '%s': %s", field, exc)
                nv = rf.value
            normed.append((rf, nv))

        # --- Step 2: Group by normalised value ---
        # Use string representation for grouping (values may not be hashable)
        groups: dict[str, list[tuple[RawField, Any]]] = {}
        for rf, nv in normed:
            key = self._group_key(nv)
            groups.setdefault(key, []).append((rf, nv))

        # --- Step 3: For each group, compute agreement confidence ---
        best_value: Optional[Any] = None
        best_conf: float = -1.0
        best_conf_score: Optional[ConfidenceScore] = None
        all_sources = [rf.source for rf, _ in normed]

        for key, group in groups.items():
            agreeing_sources = [rf.source for rf, _ in group]
            conf_score = self._confidence.compute(field, agreeing_sources, all_sources)

            if (
                conf_score.score > best_conf
                or (
                    conf_score.score == best_conf
                    and self._source_priority(agreeing_sources) > self._source_priority(
                        [rf.source for rf, _ in groups.get(
                            self._group_key(best_value), []
                        )] if best_value is not None else []
                    )
                )
            ):
                best_conf = conf_score.score
                best_conf_score = conf_score
                # Pick the representative value: highest-priority source in group
                best_rf, best_nv = max(
                    group,
                    key=lambda x: _SOURCE_PRIORITY.get(x[0].source, 0),
                )
                best_value = best_nv

        # --- Step 4: Record provenance for all candidates ---
        for rf, nv in normed:
            is_winner = self._group_key(nv) == self._group_key(best_value)
            notes = "Selected" if is_winner else (
                f"Rejected — lower confidence than winning value '{best_value}'"
            )
            self._provenance.record(
                field=field,
                source=rf.source.value,
                method=rf.method,
                raw_value=rf.raw,
                normalized_value=nv,
                confidence=rf.confidence,
                notes=notes,
            )

        logger.info(
            "Field '%s': %d candidate(s) -> winner='%s' confidence=%.2f",
            field,
            len(candidates),
            str(best_value)[:50],
            best_conf,
        )
        return best_value, best_conf_score or ConfidenceScore(field=field, score=best_conf)

    @staticmethod
    def _group_key(value: Any) -> str:
        """Produce a stable group key for a normalised value."""
        if value is None:
            return "__none__"
        if isinstance(value, str):
            return value.lower().strip()
        return str(value).lower().strip()

    @staticmethod
    def _source_priority(sources: list[SourceType]) -> int:
        """Return the maximum priority among a list of sources."""
        if not sources:
            return 0
        return max(_SOURCE_PRIORITY.get(s, 0) for s in sources)
