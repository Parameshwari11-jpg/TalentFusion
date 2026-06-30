"""
confidence.py — Confidence constants, SourceType enum, and helpers.

ALL confidence values in this project are sourced from this module.
No other module should define or hardcode confidence numerics.
"""
from __future__ import annotations

from enum import Enum
from typing import Set

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Source type enumeration
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    """Canonical identifiers for the three supported data sources."""

    ATS = "ATS"
    RESUME = "Resume"
    GITHUB = "GitHub"


# ---------------------------------------------------------------------------
# Base confidence per source
# ---------------------------------------------------------------------------

_BASE_CONFIDENCE: dict[SourceType, float] = {
    SourceType.ATS: 0.95,
    SourceType.RESUME: 0.85,
    SourceType.GITHUB: 0.80,
}

CONFIDENCE_INVALID_DATA: float = 0.20

# ---------------------------------------------------------------------------
# Agreement-bonus table  (frozenset of agreeing sources → final confidence)
# ---------------------------------------------------------------------------

_AGREEMENT_TABLE: dict[frozenset, float] = {
    frozenset({SourceType.ATS}): 0.95,
    frozenset({SourceType.RESUME}): 0.85,
    frozenset({SourceType.GITHUB}): 0.80,
    frozenset({SourceType.ATS, SourceType.RESUME}): 0.98,
    frozenset({SourceType.ATS, SourceType.GITHUB}): 0.97,
    frozenset({SourceType.RESUME, SourceType.GITHUB}): 0.93,
    frozenset({SourceType.ATS, SourceType.RESUME, SourceType.GITHUB}): 1.00,
}


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

def get_base_confidence(source: SourceType) -> float:
    """Return the standalone base confidence for a given source.

    Args:
        source: One of the supported SourceType values.

    Returns:
        Float in [0, 1].
    """
    return _BASE_CONFIDENCE.get(source, 0.80)


def get_agreement_confidence(agreeing_sources: Set[SourceType]) -> float:
    """Return the agreement-bonus confidence for a set of sources that agree.

    When multiple sources produce the same normalized value, the resulting
    confidence is higher than any individual source.  If the exact set is not
    in the table (edge case), falls back to the maximum individual base
    confidence.

    Args:
        agreeing_sources: Set of SourceType values that produced the same value.

    Returns:
        Float in [0, 1].
    """
    if not agreeing_sources:
        return 0.0
    key = frozenset(agreeing_sources)
    return _AGREEMENT_TABLE.get(
        key,
        max(get_base_confidence(s) for s in agreeing_sources),
    )


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------

class ConfidenceScore(BaseModel):
    """Per-field confidence score stored inside the canonical profile."""

    field: str = Field(description="The canonical field name this score applies to.")
    score: float = Field(ge=0.0, le=1.0, description="Confidence score in [0, 1].")
    contributing_sources: list[str] = Field(
        default_factory=list,
        description="Source names that contributed to this field.",
    )
    reasoning: str = Field(
        default="",
        description="Human-readable explanation of how the score was derived.",
    )
