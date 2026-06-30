"""
confidence_engine.py — Agreement-bonus confidence computation.

The confidence engine is responsible for:
  1. Computing the final confidence score for a field given the set of
     sources that agree on its value.
  2. Providing explanatory reasoning strings for the merge log.

All numeric constants are imported from app.models.confidence —
they are NEVER redefined here.
"""
from __future__ import annotations

from typing import Sequence

from app.models.confidence import (
    ConfidenceScore,
    SourceType,
    get_agreement_confidence,
    get_base_confidence,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConfidenceEngine:
    """Computes per-field confidence scores with agreement bonuses."""

    def compute(
        self,
        field: str,
        agreeing_sources: Sequence[SourceType],
        all_sources: Sequence[SourceType],
    ) -> ConfidenceScore:
        """Compute the final confidence score for a merged field.

        Args:
            field:            Canonical field name (for the score label).
            agreeing_sources: Sources that produced the same normalised value.
            all_sources:      All sources that had a value for this field
                              (including those that disagreed).

        Returns:
            ConfidenceScore with score, sources, and reasoning.
        """
        if not agreeing_sources:
            return ConfidenceScore(
                field=field,
                score=0.0,
                contributing_sources=[],
                reasoning="No sources produced a value for this field.",
            )

        agreeing_set = set(agreeing_sources)
        score = get_agreement_confidence(agreeing_set)

        # Build reasoning string
        source_names = sorted(s.value for s in agreeing_set)
        if len(agreeing_set) == 1:
            reasoning = (
                f"Single source ({source_names[0]}). "
                f"Base confidence: {score:.2f}."
            )
        else:
            reasoning = (
                f"Agreement between {', '.join(source_names)}. "
                f"Agreement bonus applied: {score:.2f}."
            )
        if len(all_sources) > len(agreeing_sources):
            disagreeing = [
                s.value for s in all_sources if s not in agreeing_set
            ]
            reasoning += f" Disagreeing source(s): {', '.join(disagreeing)} overridden."

        logger.debug(
            "Field '%s': agreeing=%s -> confidence=%.2f",
            field,
            source_names,
            score,
        )

        return ConfidenceScore(
            field=field,
            score=round(score, 4),
            contributing_sources=source_names,
            reasoning=reasoning,
        )

    def compute_overall(
        self,
        field_scores: dict[str, ConfidenceScore],
    ) -> float:
        """Compute a weighted average confidence across all scored fields.

        Fields with more importance (e.g. full_name, emails) could be
        weighted higher, but for now a simple mean is used.

        Args:
            field_scores: Dict of field_name → ConfidenceScore.

        Returns:
            Float in [0, 1].
        """
        if not field_scores:
            return 0.0
        total = sum(cs.score for cs in field_scores.values())
        mean = total / len(field_scores)
        return round(min(1.0, max(0.0, mean)), 4)
