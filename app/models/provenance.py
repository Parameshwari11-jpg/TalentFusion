"""
provenance.py — Provenance tracking model.

Every output field in the canonical profile records exactly where its
value came from, what raw value was observed, how it was normalised,
and with what confidence.  This enables full explainability of every
merge decision.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ProvenanceRecord(BaseModel):
    """Documents the origin and transformation of a single field value.

    Example JSON representation::

        {
            "field": "skills",
            "source": "Resume",
            "method": "resume_ocr",
            "raw_value": "JS",
            "normalized_value": "JavaScript",
            "confidence": 0.85,
            "notes": ""
        }
    """

    field: str = Field(description="Canonical field name (e.g. 'skills', 'full_name').")
    source: str = Field(description="Data source: 'ATS', 'Resume', or 'GitHub'.")
    method: str = Field(description="Extraction method (e.g. 'ats_parser', 'resume_ocr', 'github_api').")
    raw_value: Optional[Any] = Field(
        default=None,
        description="The original, un-normalised value as received from the source.",
    )
    normalized_value: Optional[Any] = Field(
        default=None,
        description="The value after normalisation (E.164 phone, YYYY-MM date, canonical skill, etc.).",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score associated with this value at time of extraction.",
    )
    notes: str = Field(
        default="",
        description="Optional explanation, e.g. 'conflict resolved: ATS overrode Resume (higher confidence)'.",
    )
