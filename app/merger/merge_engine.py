"""
merge_engine.py — Orchestrates the full merge pipeline.

Responsibilities:
  1. Receive a list of ParsedSource objects (one per parser).
  2. Apply normalisation to every raw value.
  3. Delegate scalar field merging to FieldMerger.
  4. Delegate list field merging to ListMerger.
  5. Build the CanonicalCandidate.
  6. Compute overall confidence.
  7. Write merge_log.json.

The engine is stateless except for the log accumulation per run.
A fresh run clears the provenance tracker.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from app.confidence.confidence_engine import ConfidenceEngine
from app.merger.field_merger import FieldMerger
from app.merger.list_merger import ListMerger
from app.models.candidate import (
    CanonicalCandidate,
    Links,
    Location,
    ParsedSource,
    RawField,
)
from app.models.confidence import SourceType
from app.normalizers.date_normalizer import normalize_date
from app.normalizers.email_normalizer import normalize_email
from app.normalizers.location_normalizer import normalize_location
from app.normalizers.name_normalizer import normalize_name
from app.normalizers.phone_normalizer import normalize_phone
from app.normalizers.skill_normalizer import normalize_skill
from app.provenance.provenance_tracker import ProvenanceTracker
from app.utils.helpers import is_empty, write_json_file
from app.utils.logger import get_logger
from config.settings import MERGE_LOG_PATH

logger = get_logger(__name__)


class MergeEngine:
    """Orchestrates the full multi-source merge pipeline.

    Args:
        merge_log_path: Path to write merge_log.json.
                        Defaults to project root merge_log.json.
    """

    def __init__(self, merge_log_path: Optional[Path] = None) -> None:
        self._log_path = merge_log_path or MERGE_LOG_PATH
        self._conf_engine = ConfidenceEngine()
        self._prov_tracker = ProvenanceTracker()
        self._field_merger = FieldMerger(self._conf_engine, self._prov_tracker)
        self._list_merger = ListMerger(self._conf_engine, self._prov_tracker)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def merge(self, sources: list[ParsedSource]) -> CanonicalCandidate:
        """Merge all ParsedSource objects into a single CanonicalCandidate.

        Args:
            sources: List of ParsedSource (ATS, Resume, GitHub — any subset).

        Returns:
            CanonicalCandidate — the fully merged, normalised profile.
        """
        self._prov_tracker.clear()
        merge_log: list[dict] = []

        # --- Scalar fields ---
        full_name = self._merge_full_name(sources, merge_log)
        headline = self._merge_scalar(sources, "headline", merge_log)
        years_experience = self._merge_years_experience(sources, merge_log)
        location = self._merge_location(sources, merge_log)
        links = self._merge_links(sources, merge_log)

        # --- List fields ---
        emails = self._merge_emails(sources, merge_log)
        phones = self._merge_phones(sources, merge_log, location)
        skills = self._merge_skills(sources, merge_log)
        experience = self._merge_experience(sources, merge_log)
        education = self._merge_education(sources, merge_log)

        # --- Confidence scores ---
        conf_fields = ["full_name", "headline", "years_experience", "location", "links"]
        conf_scores = {}
        all_avail_sources = [SourceType(s.source_type.value) for s in sources if s.available]
        for f in conf_fields:
            agreeing = [
                SourceType(s.source_type.value) for s in sources
                if f in s.fields and s.available
            ]
            cs = self._conf_engine.compute(f, agreeing, all_avail_sources)
            if cs.score > 0:
                conf_scores[f] = cs

        overall = self._conf_engine.compute_overall(conf_scores) if conf_scores else 0.0

        # --- Build canonical candidate ---
        candidate = CanonicalCandidate(
            candidate_id=str(uuid.uuid4()),
            full_name=full_name,
            emails=emails,
            phones=phones,
            location=location,
            links=links,
            headline=headline,
            years_experience=years_experience,
            skills=skills,
            experience=experience,
            education=education,
            provenance=self._prov_tracker.get_all(),
            confidence_scores=conf_scores,
            overall_confidence=overall,
        )

        # --- Write merge log ---
        self._write_merge_log(merge_log)

        logger.info(
            "Merge complete — candidate_id=%s, skills=%d, experience=%d, "
            "education=%d, overall_confidence=%.2f",
            candidate.candidate_id,
            len(skills),
            len(experience),
            len(education),
            overall,
        )
        return candidate

    # ------------------------------------------------------------------
    # Scalar field mergers
    # ------------------------------------------------------------------

    def _merge_full_name(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> Optional[str]:
        candidates = self._collect_scalar(sources, "full_name")
        if not candidates:
            return None

        def _norm(v: Any) -> str:
            result, _ = normalize_name(str(v))
            return result

        value, conf = self._field_merger.merge("full_name", candidates, _norm)
        if value:
            normalised, _ = normalize_name(str(value))
            log.append(self._log_entry("full_name", candidates, normalised, conf))
            return normalised
        return None

    def _merge_scalar(
        self,
        sources: list[ParsedSource],
        field: str,
        log: list[dict],
    ) -> Optional[str]:
        candidates = self._collect_scalar(sources, field)
        if not candidates:
            return None
        value, conf = self._field_merger.merge(field, candidates)
        if value is not None:
            log.append(self._log_entry(field, candidates, value, conf))
            return str(value)
        return None

    def _merge_years_experience(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> Optional[float]:
        candidates = self._collect_scalar(sources, "years_experience")
        if not candidates:
            return None

        def _norm(v: Any) -> float:
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        value, conf = self._field_merger.merge("years_experience", candidates, _norm)
        if value is not None:
            try:
                result = round(float(value), 1)
                log.append(self._log_entry("years_experience", candidates, result, conf))
                return result
            except (ValueError, TypeError):
                pass
        return None

    def _merge_location(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> Optional[Location]:
        candidates = self._collect_scalar(sources, "location")
        if not candidates:
            return None

        def _norm(v: Any) -> str:
            if isinstance(v, str):
                loc = normalize_location(v)
                return loc.raw or v
            return str(v)

        value, conf = self._field_merger.merge("location", candidates, _norm)
        if value is not None:
            loc = normalize_location(str(value))
            log.append(self._log_entry("location", candidates, loc.dict(), conf))
            return loc
        return None

    def _merge_links(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> Optional[Links]:
        """Merge link dicts from all sources — union strategy (no conflict)."""
        merged: dict[str, str] = {}
        other: list[str] = []

        for source in sources:
            if not source.available:
                continue
            rf = source.fields.get("links")
            if rf is None:
                # Also check GitHub-specific blog field
                blog_rf = source.fields.get("_github_blog")
                if blog_rf:
                    merged.setdefault("portfolio", str(blog_rf.value))
                    self._prov_tracker.record(
                        field="links",
                        source=blog_rf.source.value,
                        method=blog_rf.method,
                        raw_value=blog_rf.raw,
                        normalized_value={"portfolio": blog_rf.value},
                        confidence=blog_rf.confidence,
                        notes="Selected",
                    )
                continue

            value = rf.value if isinstance(rf, RawField) else rf
            if isinstance(value, dict):
                for k in ("linkedin", "github", "portfolio"):
                    if k in value and not is_empty(value[k]):
                        merged.setdefault(k, str(value[k]))
                for k, v in value.items():
                    if k not in ("linkedin", "github", "portfolio") and not is_empty(v):
                        if str(v) not in other:
                            other.append(str(v))
                
                # Record provenance for this individual links source
                self._prov_tracker.record(
                    field="links",
                    source=rf.source.value,
                    method=rf.method,
                    raw_value=rf.raw,
                    normalized_value=value,
                    confidence=rf.confidence,
                    notes="Selected",
                )

        if not merged and not other:
            return None

        return Links(
            linkedin=merged.get("linkedin"),
            github=merged.get("github"),
            portfolio=merged.get("portfolio"),
            other=other,
        )

    # ------------------------------------------------------------------
    # List field mergers
    # ------------------------------------------------------------------

    def _merge_emails(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> list[str]:
        raw_fields = self._collect_list(sources, "emails")
        # Also collect GitHub email stored as scalar
        for source in sources:
            rf = source.fields.get("_github_email")
            if rf and not is_empty(rf.value):
                raw_fields.append(
                    RawField(
                        value=rf.value,
                        source=rf.source,
                        confidence=rf.confidence,
                        method=rf.method,
                        raw=rf.raw,
                    )
                )

        if not raw_fields:
            return []

        # Normalise each email
        normalised_fields: list[RawField] = []
        for rf in raw_fields:
            norm, is_valid, new_conf = normalize_email(str(rf.value))
            normalised_fields.append(
                RawField(
                    value=norm,
                    source=rf.source,
                    confidence=min(rf.confidence, new_conf),
                    method=rf.method,
                    raw=rf.raw,
                )
            )

        result = self._list_merger.merge_string_list("emails", normalised_fields)
        avg_conf = sum(rf.confidence for rf in normalised_fields if rf.value in result) / len(result) if result else 0.0
        log.append({
            "field": "emails",
            "winner": ", ".join(result) if result else "None",
            "confidence": avg_conf,
            "reasoning": f"Merged and deduplicated {len(result)} email(s) from {len(normalised_fields)} source entries.",
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": str(rf.value),
                    "confidence": rf.confidence,
                }
                for rf in normalised_fields
            ]
        })
        return result

    def _merge_phones(
        self,
        sources: list[ParsedSource],
        log: list[dict],
        location: Optional[Location],
    ) -> list[str]:
        raw_fields = self._collect_list(sources, "phones")
        if not raw_fields:
            return []

        country_hint = location.country if location else None
        normalised_fields: list[RawField] = []
        for rf in raw_fields:
            norm, new_conf = normalize_phone(str(rf.value), country_hint)
            normalised_fields.append(
                RawField(
                    value=norm,
                    source=rf.source,
                    confidence=min(rf.confidence, new_conf) if new_conf < 1.0 else rf.confidence,
                    method=rf.method,
                    raw=rf.raw,
                )
            )

        result = self._list_merger.merge_string_list("phones", normalised_fields)
        avg_conf = sum(rf.confidence for rf in normalised_fields if rf.value in result) / len(result) if result else 0.0
        log.append({
            "field": "phones",
            "winner": ", ".join(result) if result else "None",
            "confidence": avg_conf,
            "reasoning": f"Merged and deduplicated {len(result)} phone number(s) from {len(normalised_fields)} source entries.",
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": str(rf.value),
                    "confidence": rf.confidence,
                }
                for rf in normalised_fields
            ]
        })
        return result

    def _merge_skills(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> list[Any]:
        raw_fields = self._collect_list(sources, "skills")
        if not raw_fields:
            return []

        skill_tuples: list[tuple[str, SourceType, str, str, float]] = []
        for rf in raw_fields:
            raw_str = str(rf.value).strip()
            canonical, was_canon, method = normalize_skill(raw_str)
            alias = raw_str if was_canon and raw_str.lower() != canonical.lower() else ""
            skill_tuples.append((canonical, rf.source, rf.method, alias, rf.confidence))

        merged = self._list_merger.merge_skills(skill_tuples)
        avg_conf = sum(s.confidence for s in merged) / len(merged) if merged else 0.0
        log.append({
            "field": "skills",
            "winner": f"{len(merged)} skills merged",
            "confidence": avg_conf,
            "reasoning": f"Merged and deduplicated {len(merged)} skill(s) across all sources.",
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": str(rf.value),
                    "confidence": rf.confidence,
                }
                for rf in raw_fields
            ]
        })
        return merged

    def _merge_experience(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> list[Any]:
        raw_fields = self._collect_list(sources, "experience")
        if not raw_fields:
            return []
        merged = self._list_merger.merge_experience(raw_fields)
        avg_conf = sum(e.confidence for e in merged) / len(merged) if merged else 0.0
        log.append({
            "field": "experience",
            "winner": f"{len(merged)} roles merged",
            "confidence": avg_conf,
            "reasoning": f"Merged and chronologically ordered {len(merged)} work experience entry/entries.",
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": f"{rf.value.get('title', 'Unknown')} @ {rf.value.get('company', 'Unknown')}" if isinstance(rf.value, dict) else str(rf.value),
                    "confidence": rf.confidence,
                }
                for rf in raw_fields
            ]
        })
        return merged

    def _merge_education(
        self,
        sources: list[ParsedSource],
        log: list[dict],
    ) -> list[Any]:
        raw_fields = self._collect_list(sources, "education")
        if not raw_fields:
            return []
        merged = self._list_merger.merge_education(raw_fields)
        avg_conf = sum(e.confidence for e in merged) / len(merged) if merged else 0.0
        log.append({
            "field": "education",
            "winner": f"{len(merged)} education records merged",
            "confidence": avg_conf,
            "reasoning": f"Merged and deduplicated {len(merged)} education entry/entries.",
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": f"{rf.value.get('degree', '')} @ {rf.value.get('institution', 'Unknown')}" if isinstance(rf.value, dict) else str(rf.value),
                    "confidence": rf.confidence,
                }
                for rf in raw_fields
            ]
        })
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_scalar(
        sources: list[ParsedSource],
        field: str,
    ) -> list[RawField]:
        """Collect all RawField values for a scalar field from all sources."""
        result: list[RawField] = []
        for source in sources:
            if not source.available:
                continue
            rf = source.fields.get(field)
            if rf is not None and not is_empty(rf.value if hasattr(rf, 'value') else rf):
                result.append(rf)
        return result

    @staticmethod
    def _collect_list(
        sources: list[ParsedSource],
        field: str,
    ) -> list[RawField]:
        """Collect all RawField values for a list field from all sources."""
        result: list[RawField] = []
        for source in sources:
            if not source.available:
                continue
            items = source.list_fields.get(field, [])
            for item in items:
                if item is not None:
                    result.append(item)
        return result

    @staticmethod
    def _log_entry(
        field: str,
        candidates: list[RawField],
        winner: Any,
        conf: Any,
    ) -> dict:
        """Build a merge log entry for a scalar field."""
        return {
            "field": field,
            "candidates": [
                {
                    "source": rf.source.value,
                    "value": str(rf.value)[:200],
                    "confidence": rf.confidence,
                }
                for rf in candidates
            ],
            "winner": str(winner)[:200],
            "confidence": conf.score if hasattr(conf, "score") else conf,
            "reasoning": conf.reasoning if hasattr(conf, "reasoning") else "",
        }

    def _write_merge_log(self, log: list[dict]) -> None:
        """Persist the merge log to merge_log.json."""
        success = write_json_file(self._log_path, log)
        if success:
            logger.info("Merge log written to %s", self._log_path)
        else:
            logger.warning("Failed to write merge log to %s", self._log_path)
