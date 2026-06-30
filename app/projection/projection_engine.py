"""
projection_engine.py — Config-driven output shaping.

The projection engine takes a CanonicalCandidate (source-independent)
and a runtime JSON configuration, then produces the final output dict.

The canonical model is NEVER modified — projection is a read-only
transformation.

Config schema:
    {
        "fields": ["full_name", "emails", ...],  // fields to include
        "rename": {"full_name": "name"},          // rename output keys
        "include_confidence": true,               // attach confidence scores
        "include_provenance": true,               // attach provenance records
        "missing_field_policy": "null"            // "null" | "omit" | "error"
    }
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.candidate import CanonicalCandidate
from app.utils.logger import get_logger
from config.settings import (
    ALL_CANONICAL_FIELDS,
    POLICY_ERROR,
    POLICY_NULL,
    POLICY_OMIT,
    VALID_MISSING_POLICIES,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------

class ProjectionConfig(BaseModel):
    """Runtime configuration for the projection engine.

    Attributes:
        fields:                 List of canonical field names to include.
                                Defaults to all canonical fields.
        rename:                 Map of canonical_name → output_key.
        include_confidence:     Whether to include per-field confidence scores.
        include_provenance:     Whether to include the provenance list.
        missing_field_policy:   What to do when a field has no value.
                                'null'  → include key with null value
                                'omit'  → exclude key entirely
                                'error' → raise ValueError
    """

    fields: list[str] = Field(default_factory=lambda: list(ALL_CANONICAL_FIELDS))
    rename: dict[str, str] = Field(default_factory=dict)
    include_confidence: bool = True
    include_provenance: bool = True
    missing_field_policy: str = POLICY_NULL

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectionConfig":
        """Build a ProjectionConfig from a plain dict (e.g. loaded from JSON).

        Unknown fields are silently ignored.  Missing fields use defaults.

        Args:
            data: Dict loaded from the output_config.json file.

        Returns:
            ProjectionConfig instance.
        """
        # Filter out comment fields
        clean = {k: v for k, v in data.items() if not k.startswith("_")}

        policy = clean.get("missing_field_policy", POLICY_NULL)
        if policy not in VALID_MISSING_POLICIES:
            logger.warning(
                "Invalid missing_field_policy '%s' — defaulting to 'null'.", policy
            )
            clean["missing_field_policy"] = POLICY_NULL

        return cls(**{k: v for k, v in clean.items() if k in cls.model_fields})

    @classmethod
    def default(cls) -> "ProjectionConfig":
        """Return the default projection config (all fields, with confidence+provenance)."""
        return cls()


# ---------------------------------------------------------------------------
# Projection Engine
# ---------------------------------------------------------------------------

class ProjectionEngine:
    """Applies a ProjectionConfig to a CanonicalCandidate to produce output JSON."""

    def project(
        self,
        candidate: CanonicalCandidate,
        config: Optional[ProjectionConfig] = None,
    ) -> dict[str, Any]:
        """Project a CanonicalCandidate to an output dict.

        Args:
            candidate: The fully merged canonical profile.
            config:    Projection configuration.  Uses default if None.

        Returns:
            Output dict shaped according to the config.

        Raises:
            ValueError: If missing_field_policy is 'error' and a field is None.
        """
        cfg = config or ProjectionConfig.default()
        raw = candidate.model_dump(mode="python")

        output: dict[str, Any] = {}

        # Always include candidate_id (not in the user-facing fields list, but required)
        output["candidate_id"] = raw.get("candidate_id")

        for field in cfg.fields:
            if field == "candidate_id":
                continue  # Already added

            # Resolve value
            value = self._get_field_value(field, raw, candidate, cfg)

            # Apply missing field policy
            if value is None:
                if cfg.missing_field_policy == POLICY_ERROR:
                    raise ValueError(
                        f"Field '{field}' has no value and missing_field_policy='error'."
                    )
                elif cfg.missing_field_policy == POLICY_OMIT:
                    logger.debug("Field '%s' omitted (null, policy=omit).", field)
                    continue
                else:  # POLICY_NULL
                    pass  # value stays None

            # Rename key if configured
            output_key = cfg.rename.get(field, field)
            output[output_key] = value

        # Confidence scores
        if cfg.include_confidence:
            output["confidence_scores"] = {
                k: {
                    "score": v.score,
                    "sources": v.contributing_sources,
                    "reasoning": v.reasoning,
                }
                for k, v in candidate.confidence_scores.items()
            }

        # Provenance
        if cfg.include_provenance and "provenance" in cfg.fields:
            # Already included in field loop
            pass
        elif cfg.include_provenance and "provenance" not in cfg.fields:
            output["provenance"] = [
                p.model_dump() for p in candidate.provenance
            ]

        logger.info(
            "Projection complete — %d output fields, confidence=%s, provenance=%s",
            len(output),
            cfg.include_confidence,
            cfg.include_provenance,
        )
        return output

    @staticmethod
    def _get_field_value(
        field: str,
        raw: dict[str, Any],
        candidate: CanonicalCandidate,
        cfg: ProjectionConfig,
    ) -> Any:
        """Retrieve and serialise a field value from the canonical candidate.

        Args:
            field:     Canonical field name.
            raw:       model_dump() output of the candidate.
            candidate: The CanonicalCandidate object.
            cfg:       Active projection config.

        Returns:
            Serialised value suitable for JSON output.
        """
        if field == "provenance":
            if cfg.include_provenance:
                return [p.model_dump() for p in candidate.provenance]
            return None

        if field == "overall_confidence":
            return candidate.overall_confidence

        if field == "skills":
            return [
                {
                    "name": s.name,
                    "confidence": s.confidence,
                    "sources": s.sources,
                    **({"aliases": s.aliases_found} if s.aliases_found else {}),
                }
                for s in candidate.skills
            ]

        if field == "experience":
            return [
                {k: v for k, v in e.model_dump().items()
                 if v is not None and k not in ("confidence", "source")}
                for e in candidate.experience
            ]

        if field == "education":
            return [
                {k: v for k, v in e.model_dump().items()
                 if v is not None and k not in ("confidence", "source")}
                for e in candidate.education
            ]

        if field == "location":
            loc = candidate.location
            if loc is None:
                return None
            return {k: v for k, v in loc.model_dump().items() if v is not None}

        if field == "links":
            links = candidate.links
            if links is None:
                return None
            return {k: v for k, v in links.model_dump().items()
                    if v is not None and v != []}

        # Default: return raw value as-is
        value = raw.get(field)
        return value


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def project(
    candidate: CanonicalCandidate,
    config_dict: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Convenience function: project with an optional config dict.

    Args:
        candidate:   CanonicalCandidate to project.
        config_dict: Optional projection config as a plain dict.
                     If None, uses all defaults.

    Returns:
        Output dict.
    """
    cfg = ProjectionConfig.from_dict(config_dict) if config_dict else ProjectionConfig.default()
    return ProjectionEngine().project(candidate, cfg)
