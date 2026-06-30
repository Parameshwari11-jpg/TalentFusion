"""
list_merger.py — Deduplication and merging for list fields.

Handles:
  - skills: canonical deduplication by name, confidence union
  - emails: deduplication by lowercase value
  - phones: deduplication by normalised E.164 value
  - experience: soft deduplication by company+title
  - education: soft deduplication by institution+degree
"""
from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from app.models.candidate import Education, Experience, RawField, Skill
from app.models.confidence import ConfidenceScore, SourceType
from app.confidence.confidence_engine import ConfidenceEngine
from app.provenance.provenance_tracker import ProvenanceTracker
from app.utils.helpers import is_empty, normalize_whitespace, slugify
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ListMerger:
    """Merges list-type fields (skills, emails, phones, experience, education).

    Args:
        confidence_engine:  For computing per-item confidence scores.
        provenance_tracker: For recording all merge decisions.
    """

    def __init__(
        self,
        confidence_engine: ConfidenceEngine,
        provenance_tracker: ProvenanceTracker,
    ) -> None:
        self._confidence = confidence_engine
        self._provenance = provenance_tracker

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def merge_skills(
        self,
        skill_raw_fields: list[tuple[str, SourceType, str, str, float]],
    ) -> list[Skill]:
        """Merge skill RawFields into deduplicated Skill models.

        Args:
            skill_raw_fields: List of (canonical_name, source, method, alias_found, confidence).

        Returns:
            Deduplicated list of Skill models, sorted by confidence desc.
        """
        # Group by canonical skill name (slugified for deduplication)
        groups: dict[str, dict] = {}
        for canonical, source, method, alias, confidence in skill_raw_fields:
            key = slugify(canonical)
            if key not in groups:
                groups[key] = {
                    "name": canonical,
                    "sources": [],
                    "aliases": [],
                    "raw_fields": [],
                }
            if source not in groups[key]["sources"]:
                groups[key]["sources"].append(source)
            if alias and alias.lower() != canonical.lower():
                groups[key]["aliases"].append(alias)
            groups[key]["raw_fields"].append({
                "source": source,
                "method": method,
                "alias": alias,
                "confidence": confidence,
            })

        skills: list[Skill] = []
        for key, data in groups.items():
            source_enums = [
                SourceType(s) if isinstance(s, str) else s
                for s in data["sources"]
            ]
            conf_score = self._confidence.compute(
                field=f"skill:{data['name']}",
                agreeing_sources=source_enums,
                all_sources=source_enums,
            )
            skill = Skill(
                name=data["name"],
                aliases_found=list(dict.fromkeys(data["aliases"])),
                confidence=conf_score.score,
                sources=[s.value if hasattr(s, "value") else s for s in data["sources"]],
            )
            skills.append(skill)
            # Record provenance for all contributing raw fields
            # Determine the highest-confidence raw field as the representative winner
            if data.get("raw_fields"):
                best_rf = max(data["raw_fields"], key=lambda x: x["confidence"])
                for rf in data["raw_fields"]:
                    is_best = (rf == best_rf)
                    notes = "Selected" if is_best else f"Merged with selected skill from source '{best_rf['source'].value}'"
                    self._provenance.record(
                        field="skills",
                        source=rf["source"].value,
                        method=rf["method"],
                        raw_value=rf["alias"] or data["name"],
                        normalized_value=data["name"],
                        confidence=rf["confidence"],
                        notes=notes,
                    )
            else:
                self._provenance.record(
                    field="skills",
                    source=", ".join(skill.sources),
                    method="list_merger",
                    raw_value=data["aliases"] or [data["name"]],
                    normalized_value=data["name"],
                    confidence=conf_score.score,
                    notes=f"Deduplicated from {len(data['sources'])} source(s).",
                )

        # Sort: confidence descending, then alphabetically
        skills.sort(key=lambda s: (-s.confidence, s.name.lower()))
        logger.info("Merged %d unique skills.", len(skills))
        return skills

    # ------------------------------------------------------------------
    # Simple list fields: emails, phones
    # ------------------------------------------------------------------

    def merge_string_list(
        self,
        field: str,
        raw_fields: list[RawField],
    ) -> list[str]:
        """Merge and deduplicate a list of string values.

        Uses lowercase comparison for deduplication.

        Args:
            field:      Canonical field name (for provenance).
            raw_fields: All RawField[str] from all sources.

        Returns:
            Deduplicated list of strings, preserving the first occurrence
            (highest-priority source first).
        """
        seen: set[str] = set()
        result: list[str] = []

        # Sort by source priority so highest-priority source's value wins
        sorted_fields = sorted(
            raw_fields,
            key=lambda rf: -{"ATS": 3, "Resume": 2, "GitHub": 1}.get(
                rf.source.value, 0
            ),
        )

        for rf in sorted_fields:
            value = str(rf.value).strip()
            key = value.lower()
            if key not in seen:
                seen.add(key)
                result.append(value)
                self._provenance.record(
                    field=field,
                    source=rf.source.value,
                    method=rf.method,
                    raw_value=rf.raw,
                    normalized_value=value,
                    confidence=rf.confidence,
                    notes="Selected",
                )
            else:
                self._provenance.record(
                    field=field,
                    source=rf.source.value,
                    method=rf.method,
                    raw_value=rf.raw,
                    normalized_value=value,
                    confidence=rf.confidence,
                    notes="Rejected — duplicate of value from higher-priority source",
                )

        logger.debug("Merged %s list: %d unique values.", field, len(result))
        return result

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------

    def merge_experience(
        self,
        raw_fields: list[RawField],
    ) -> list[Experience]:
        """Merge experience entries with soft deduplication.
        If two sources have the same/repeated experience, the one with higher confidence is kept,
        and missing fields in it are filled from the lower confidence entry.
        """
        # Sort by confidence descending so higher confidence entries are processed first
        sorted_fields = sorted(
            raw_fields,
            key=lambda rf: rf.confidence,
            reverse=True,
        )

        merged_entries: list[tuple[dict, SourceType, str, float]] = []

        for rf in sorted_fields:
            entry: dict = rf.value if isinstance(rf.value, dict) else {}
            company = str(entry.get("company", "")).strip()
            title = str(entry.get("title", "")).strip()
            if not company and not title:
                continue

            # Check if this matches any already merged entry (fuzzy matching on company + title)
            duplicate = False
            for idx, (existing_entry, existing_source, existing_method, existing_conf) in enumerate(merged_entries):
                ext_company = str(existing_entry.get("company", "")).strip()
                ext_title = str(existing_entry.get("title", "")).strip()

                # If company names match (fuzzy) and titles are similar
                comp_match = (fuzz.token_set_ratio(company.lower(), ext_company.lower()) >= 85 or
                              company.lower() in ext_company.lower() or
                              ext_company.lower() in company.lower())
                
                title_match = (not title or not ext_title or 
                               fuzz.token_set_ratio(title.lower(), ext_title.lower()) >= 80 or
                               title.lower() in ext_title.lower() or
                               ext_title.lower() in title.lower())

                if comp_match and title_match:
                    duplicate = True
                    # Merge fields from the lower-confidence entry (rf) into the higher-confidence entry
                    merged_entries[idx] = (
                        self._merge_dicts(existing_entry, entry),
                        existing_source,
                        existing_method,
                        existing_conf
                    )
                    # Record provenance for the merged duplicate record
                    self._provenance.record(
                        field="experience",
                        source=rf.source.value,
                        method=rf.method,
                        raw_value=entry,
                        normalized_value=f"{entry.get('title', '')} @ {company}",
                        confidence=rf.confidence,
                        notes=f"Merged into entry from higher-confidence source '{existing_source.value}'",
                    )
                    break

            if not duplicate:
                merged_entries.append((entry, rf.source, rf.method, rf.confidence))

        experiences: list[Experience] = []
        for entry, source, method, confidence in merged_entries:
            try:
                exp = self._dict_to_experience(entry, source, confidence)
                experiences.append(exp)
                self._provenance.record(
                    field="experience",
                    source=source.value,
                    method=method,
                    raw_value=entry,
                    normalized_value=f"{exp.title} @ {exp.company}",
                    confidence=confidence,
                )
            except Exception as exc:
                logger.warning("Could not build Experience from %s: %s", entry, exc)

        # Sort most recent first (by start_date desc)
        experiences.sort(
            key=lambda e: (e.start_date or "0000-00"),
            reverse=True,
        )
        return experiences

    @staticmethod
    def _merge_dicts(high_conf: dict, low_conf: dict) -> dict:
        """Merge two dicts, keeping values from high_conf but filling missing fields from low_conf."""
        merged = high_conf.copy()
        for k, v in low_conf.items():
            if is_empty(merged.get(k)) and not is_empty(v):
                merged[k] = v
        return merged

    @staticmethod
    def _dict_to_experience(
        entry: dict, source: SourceType, confidence: float
    ) -> Experience:
        """Convert a raw dict to an Experience model, applying date normalisation."""
        from app.normalizers.date_normalizer import normalize_date

        def safe_date(raw: Any) -> str | None:
            if raw is None:
                return None
            normalised, ok = normalize_date(str(raw))
            return normalised

        return Experience(
            company=str(entry.get("company", "Unknown")).strip(),
            title=str(entry.get("title", "Unknown")).strip(),
            start_date=safe_date(entry.get("start_date")),
            end_date=safe_date(entry.get("end_date")),
            description=entry.get("description"),
            location=entry.get("location"),
            confidence=confidence,
            source=source.value,
        )

    # ------------------------------------------------------------------
    # Education
    # ------------------------------------------------------------------

    def merge_education(
        self,
        raw_fields: list[RawField],
    ) -> list[Education]:
        """Merge education entries with soft deduplication.
        If two sources have the same/repeated education, the one with higher confidence is kept,
        and missing fields in it are filled from the lower confidence entry.
        """
        # Sort by confidence descending so higher confidence entries are processed first
        sorted_fields = sorted(
            raw_fields,
            key=lambda rf: rf.confidence,
            reverse=True,
        )

        merged_entries: list[tuple[dict, SourceType, str, float]] = []

        for rf in sorted_fields:
            entry: dict = rf.value if isinstance(rf.value, dict) else {}
            institution = str(entry.get("institution", "")).strip()
            if not institution:
                continue

            # Check if this matches any already merged entry (fuzzy matching on institution name)
            duplicate = False
            for idx, (existing_entry, existing_source, existing_method, existing_conf) in enumerate(merged_entries):
                ext_inst = str(existing_entry.get("institution", "")).strip()

                # If institution names are very similar
                inst_match = (fuzz.token_set_ratio(institution.lower(), ext_inst.lower()) >= 85 or
                              institution.lower() in ext_inst.lower() or
                              ext_inst.lower() in institution.lower())

                if inst_match:
                    duplicate = True
                    # Merge fields from the lower-confidence entry (rf) into the higher-confidence entry
                    merged_entries[idx] = (
                        self._merge_dicts(existing_entry, entry),
                        existing_source,
                        existing_method,
                        existing_conf
                    )
                    # Record provenance for the merged duplicate record
                    self._provenance.record(
                        field="education",
                        source=rf.source.value,
                        method=rf.method,
                        raw_value=entry,
                        normalized_value=f"{entry.get('degree', '')} @ {institution}",
                        confidence=rf.confidence,
                        notes=f"Merged into entry from higher-confidence source '{existing_source.value}'",
                    )
                    break

            if not duplicate:
                merged_entries.append((entry, rf.source, rf.method, rf.confidence))

        educations: list[Education] = []
        for entry, source, method, confidence in merged_entries:
            try:
                edu = self._dict_to_education(entry, source, confidence)
                educations.append(edu)
                self._provenance.record(
                    field="education",
                    source=source.value,
                    method=method,
                    raw_value=entry,
                    normalized_value=f"{edu.degree or ''} @ {edu.institution}",
                    confidence=confidence,
                )
            except Exception as exc:
                logger.warning("Could not build Education from %s: %s", entry, exc)

        return educations

    @staticmethod
    def _dict_to_education(
        entry: dict, source: SourceType, confidence: float
    ) -> Education:
        from app.normalizers.date_normalizer import normalize_date

        def safe_date(raw: Any) -> str | None:
            if raw is None:
                return None
            # Handle plain year "2019" → "2019-01"
            normalised, ok = normalize_date(str(raw))
            return normalised

        gpa_raw = entry.get("gpa")
        gpa: float | None = None
        if gpa_raw is not None:
            if isinstance(gpa_raw, (int, float)):
                gpa = float(gpa_raw)
            elif isinstance(gpa_raw, str):
                import re
                match = re.search(r"(\d+(?:\.\d+)?)", gpa_raw)
                if match:
                    try:
                        gpa = float(match.group(1))
                    except ValueError:
                        pass
                pass

        return Education(
            institution=str(entry.get("institution", "Unknown")).strip(),
            degree=entry.get("degree"),
            field_of_study=entry.get("field_of_study"),
            start_date=safe_date(entry.get("start_date")),
            end_date=safe_date(entry.get("end_date")),
            gpa=gpa,
            confidence=confidence,
            source=source.value,
        )
