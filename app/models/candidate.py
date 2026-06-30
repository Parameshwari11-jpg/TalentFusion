"""
candidate.py — Core Pydantic models for the candidate data pipeline.

Layer structure
───────────────
  RawField[T]          Intermediate: a parsed value tagged with source + confidence.
                       Used internally by parsers and the merge engine.
                       NEVER appears in canonical output.

  ParsedSource         Everything a single parser returns (a dict of RawFields).

  Location             Normalised location sub-model.
  Links                Normalised links sub-model.
  Skill                A single canonical skill with confidence + sources.
  Experience           A single work-experience entry.
  Education            A single education entry.

  CanonicalCandidate   The final merged profile.  Output-config-independent.
                       This is what the projection engine receives.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.confidence import ConfidenceScore, SourceType
from app.models.provenance import ProvenanceRecord

# ---------------------------------------------------------------------------
# Generic type variable for RawField
# ---------------------------------------------------------------------------

T = TypeVar("T")


# ---------------------------------------------------------------------------
# RawField — intermediate carrier, not part of canonical output
# ---------------------------------------------------------------------------

class RawField(BaseModel, Generic[T]):
    """A parsed value tagged with its source, method, and confidence.

    This is the lingua franca between parsers and the merge engine.
    The merge engine collects RawField instances from all sources for
    each canonical field, then resolves conflicts.

    Attributes:
        value:       The parsed (and already normalised) value.
        source:      Which source produced this value.
        confidence:  Base confidence assigned by the parser.
        method:      Parser identifier (e.g. 'ats_parser').
        raw:         Original, un-normalised value for provenance logging.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T
    source: SourceType
    confidence: float = Field(ge=0.0, le=1.0)
    method: str
    raw: Optional[Any] = Field(
        default=None,
        description="The original value before normalisation.",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RawField(value={self.value!r}, source={self.source.value!r}, "
            f"confidence={self.confidence:.2f})"
        )


# ---------------------------------------------------------------------------
# ParsedSource — what each parser returns
# ---------------------------------------------------------------------------

class ParsedSource(BaseModel):
    """The complete output of a single parser run.

    Each parser (ATS, Resume, GitHub) produces one ParsedSource.
    ``fields`` maps canonical field names to ``RawField[Any]`` instances.
    The merge engine collects all ParsedSource objects and resolves them
    into a single CanonicalCandidate.

    Attributes:
        source_type:   Which source this belongs to.
        fields:        Canonical field name → RawField.
        list_fields:   Canonical list-field name → list[RawField[Any]].
                       Used for skills, emails, phones, experience, education.
        parse_errors:  Non-fatal errors encountered during parsing.
        available:     False if the source was missing or completely failed.
    """

    source_type: SourceType
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Scalar canonical fields → RawField[Any].",
    )
    list_fields: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="List canonical fields → list[RawField[Any]].",
    )
    parse_errors: list[str] = Field(default_factory=list)
    available: bool = Field(
        default=True,
        description="False when the source was completely unavailable.",
    )


# ---------------------------------------------------------------------------
# Sub-models — Location, Links
# ---------------------------------------------------------------------------

class Location(BaseModel):
    """Normalised geographic location.

    Attributes:
        city:    City name (as provided, trimmed).
        state:   State / province (as provided, trimmed).
        country: ISO-3166 Alpha-2 country code (e.g. 'US', 'IN').
        raw:     Original location string before normalisation.
    """

    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = Field(
        default=None,
        description="ISO-3166 Alpha-2 country code.",
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
    )
    raw: Optional[str] = None

    @field_validator("country", mode="before")
    @classmethod
    def uppercase_country(cls, v: Optional[str]) -> Optional[str]:
        """Ensure country codes are always uppercase."""
        return v.strip().upper() if isinstance(v, str) and v.strip() else None


class Links(BaseModel):
    """Collection of profile / social links.

    Attributes:
        linkedin:  LinkedIn profile URL.
        github:    GitHub profile URL.
        portfolio: Personal website or portfolio URL.
        other:     Any other links found.
    """

    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

class Skill(BaseModel):
    """A single canonical skill entry in the merged profile.

    Attributes:
        name:          Canonical skill name (e.g. 'JavaScript').
        aliases_found: Raw alias strings that were mapped to this skill.
        confidence:    Final merged confidence for this skill.
        sources:       Which sources mentioned this skill.
    """

    name: str = Field(description="Canonical skill name.")
    aliases_found: list[str] = Field(
        default_factory=list,
        description="Raw strings that resolved to this skill.",
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    sources: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------

class Experience(BaseModel):
    """A single work-experience entry.

    Attributes:
        company:     Employer name.
        title:       Job title / role.
        start_date:  Normalised start date in YYYY-MM format.
        end_date:    Normalised end date in YYYY-MM format, or 'Present'.
        description: Responsibilities / summary.
        location:    Office location string.
        confidence:  Source confidence at time of extraction.
        source:      Which source this entry came from.
    """

    company: str
    title: str
    start_date: Optional[str] = Field(
        default=None,
        description="YYYY-MM formatted start date.",
        pattern=r"^\d{4}-\d{2}$|^Present$",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="YYYY-MM formatted end date, or 'Present'.",
        pattern=r"^\d{4}-\d{2}$|^Present$",
    )
    description: Optional[str] = None
    location: Optional[str] = None
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: Optional[str] = None

    @field_validator("company", "title", mode="before")
    @classmethod
    def strip_strings(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

class Education(BaseModel):
    """A single education entry.

    Attributes:
        institution:    Name of the school, university, or college.
        degree:         Degree type (e.g. 'Bachelor of Technology').
        field_of_study: Major / discipline.
        start_date:     YYYY-MM formatted start date.
        end_date:       YYYY-MM formatted end / graduation date.
        gpa:            Grade point average (if available).
        confidence:     Source confidence at time of extraction.
        source:         Which source this entry came from.
    """

    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}$|^Present$",
    )
    end_date: Optional[str] = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}$|^Present$",
    )
    gpa: Optional[float] = Field(default=None, ge=0.0)
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    source: Optional[str] = None

    @field_validator("institution", mode="before")
    @classmethod
    def strip_institution(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# CanonicalCandidate — the final merged profile
# ---------------------------------------------------------------------------

class CanonicalCandidate(BaseModel):
    """The single, trusted candidate profile produced by the merge engine.

    This model is completely independent of any output configuration.
    The projection engine consumes this model and shapes the final JSON
    according to a runtime configuration.

    Attributes:
        candidate_id:       UUID assigned at creation time.
        full_name:          Normalised full name (Title Case, trimmed).
        emails:             Deduplicated list of email addresses.
        phones:             Deduplicated list of phone numbers (E.164 where possible).
        location:           Normalised location sub-model.
        links:              Profile links (LinkedIn, GitHub, portfolio, other).
        headline:           Professional headline / current title.
        years_experience:   Total years of work experience (float for precision).
        skills:             Deduplicated list of canonical Skill entries.
        experience:         Chronological list of Experience entries.
        education:          List of Education entries.
        provenance:         Full provenance trail for every field.
        confidence_scores:  Per-field confidence scores.
        overall_confidence: Weighted average confidence across all fields.
        created_at:         ISO-8601 UTC timestamp of profile creation.
    """

    candidate_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this candidate profile.",
    )
    full_name: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: Optional[str] = None
    years_experience: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total years of professional experience.",
    )
    skills: list[Skill] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    confidence_scores: dict[str, ConfidenceScore] = Field(default_factory=dict)
    overall_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean confidence across all scored fields.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 UTC timestamp when the profile was created.",
    )

    def get_provenance_for(self, field: str) -> list[ProvenanceRecord]:
        """Return all provenance records for a given field name.

        Args:
            field: Canonical field name (e.g. 'skills', 'full_name').

        Returns:
            Filtered list of ProvenanceRecord instances.
        """
        return [p for p in self.provenance if p.field == field]

    def get_confidence_for(self, field: str) -> float:
        """Return the confidence score for a given field, or 0.0 if unknown.

        Args:
            field: Canonical field name.

        Returns:
            Float in [0, 1].
        """
        cs = self.confidence_scores.get(field)
        return cs.score if cs else 0.0
