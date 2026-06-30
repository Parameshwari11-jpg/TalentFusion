"""
provenance_tracker.py — Provenance record builder.

Builds ProvenanceRecord objects during merging and provides
helper methods to query provenance after the fact.
"""
from __future__ import annotations

from typing import Any, Optional

from app.models.provenance import ProvenanceRecord
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ProvenanceTracker:
    """Accumulates provenance records during the merge process."""

    def __init__(self) -> None:
        self._records: list[ProvenanceRecord] = []

    def record(
        self,
        field: str,
        source: str,
        method: str,
        raw_value: Optional[Any] = None,
        normalized_value: Optional[Any] = None,
        confidence: float = 0.0,
        notes: str = "",
    ) -> ProvenanceRecord:
        """Create and store a provenance record.

        Args:
            field:             Canonical field name.
            source:            Source label ('ATS', 'Resume', 'GitHub').
            method:            Parser/extraction method identifier.
            raw_value:         Original un-normalised value.
            normalized_value:  Value after normalisation.
            confidence:        Confidence score at time of extraction.
            notes:             Human-readable explanation of any decisions.

        Returns:
            The created ProvenanceRecord.
        """
        record = ProvenanceRecord(
            field=field,
            source=source,
            method=method,
            raw_value=raw_value,
            normalized_value=normalized_value,
            confidence=round(confidence, 4),
            notes=notes,
        )
        self._records.append(record)
        logger.debug(
            "Provenance: field='%s' source='%s' confidence=%.2f notes='%s'",
            field, source, confidence, notes[:60],
        )
        return record

    def get_all(self) -> list[ProvenanceRecord]:
        """Return all accumulated provenance records."""
        return list(self._records)

    def get_for_field(self, field: str) -> list[ProvenanceRecord]:
        """Return provenance records for a specific field."""
        return [r for r in self._records if r.field == field]

    def clear(self) -> None:
        """Reset the tracker (useful between pipeline runs)."""
        self._records.clear()
