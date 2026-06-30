"""
test_projection.py — Unit tests for the projection engine and config model.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.candidate import CanonicalCandidate, Skill, Location, Links
from app.projection.projection_engine import ProjectionConfig, ProjectionEngine, project
from config.settings import POLICY_NULL, POLICY_OMIT, POLICY_ERROR


def _make_candidate(**kwargs) -> CanonicalCandidate:
    defaults = {
        "full_name": "Alice Johnson",
        "emails": ["alice@example.com"],
        "phones": ["+16505550192"],
        "headline": "Senior Engineer",
        "years_experience": 5.0,
        "overall_confidence": 0.95,
    }
    defaults.update(kwargs)
    return CanonicalCandidate(**defaults)


class TestProjectionConfig:
    def test_default_config_includes_all_fields(self):
        cfg = ProjectionConfig.default()
        assert "full_name" in cfg.fields
        assert "skills" in cfg.fields
        assert cfg.include_confidence is True
        assert cfg.include_provenance is True
        assert cfg.missing_field_policy == POLICY_NULL

    def test_from_dict(self):
        cfg = ProjectionConfig.from_dict({
            "fields": ["full_name", "emails"],
            "rename": {"full_name": "name"},
            "include_confidence": False,
            "include_provenance": False,
            "missing_field_policy": "omit",
        })
        assert cfg.fields == ["full_name", "emails"]
        assert cfg.rename == {"full_name": "name"}
        assert cfg.include_confidence is False
        assert cfg.missing_field_policy == POLICY_OMIT

    def test_from_dict_invalid_policy_defaults_to_null(self):
        cfg = ProjectionConfig.from_dict({"missing_field_policy": "invalid"})
        assert cfg.missing_field_policy == POLICY_NULL

    def test_from_dict_ignores_comment_fields(self):
        cfg = ProjectionConfig.from_dict({
            "_comment": "This is a comment",
            "fields": ["full_name"],
        })
        assert "_comment" not in cfg.fields


class TestProjectionEngine:
    def setup_method(self):
        self.engine = ProjectionEngine()

    def test_project_selected_fields(self):
        candidate = _make_candidate()
        cfg = ProjectionConfig(fields=["full_name", "emails"], include_confidence=False, include_provenance=False)
        output = self.engine.project(candidate, cfg)
        assert "full_name" in output or "name" in output
        assert "emails" in output
        assert "headline" not in output

    def test_rename_field(self):
        candidate = _make_candidate()
        cfg = ProjectionConfig(
            fields=["full_name"],
            rename={"full_name": "name"},
            include_confidence=False,
            include_provenance=False,
        )
        output = self.engine.project(candidate, cfg)
        assert "name" in output
        assert "full_name" not in output

    def test_missing_field_policy_null(self):
        candidate = _make_candidate(full_name=None)
        cfg = ProjectionConfig(
            fields=["full_name"],
            missing_field_policy=POLICY_NULL,
            include_confidence=False,
            include_provenance=False,
        )
        output = self.engine.project(candidate, cfg)
        assert "full_name" in output
        assert output["full_name"] is None

    def test_missing_field_policy_omit(self):
        candidate = _make_candidate(full_name=None)
        cfg = ProjectionConfig(
            fields=["full_name"],
            missing_field_policy=POLICY_OMIT,
            include_confidence=False,
            include_provenance=False,
        )
        output = self.engine.project(candidate, cfg)
        assert "full_name" not in output

    def test_missing_field_policy_error(self):
        candidate = _make_candidate(full_name=None)
        cfg = ProjectionConfig(
            fields=["full_name"],
            missing_field_policy=POLICY_ERROR,
            include_confidence=False,
            include_provenance=False,
        )
        with pytest.raises(ValueError):
            self.engine.project(candidate, cfg)

    def test_candidate_id_always_included(self):
        candidate = _make_candidate()
        cfg = ProjectionConfig(fields=["full_name"], include_confidence=False, include_provenance=False)
        output = self.engine.project(candidate, cfg)
        assert "candidate_id" in output

    def test_skills_serialised_correctly(self):
        candidate = _make_candidate(
            skills=[Skill(name="Python", confidence=0.95, sources=["ATS"])]
        )
        cfg = ProjectionConfig(fields=["skills"], include_confidence=False, include_provenance=False)
        output = self.engine.project(candidate, cfg)
        assert "skills" in output
        assert output["skills"][0]["name"] == "Python"

    def test_location_serialised_correctly(self):
        candidate = _make_candidate(
            location=Location(city="San Francisco", country="US", raw="San Francisco, US")
        )
        cfg = ProjectionConfig(fields=["location"], include_confidence=False, include_provenance=False)
        output = self.engine.project(candidate, cfg)
        assert output["location"]["city"] == "San Francisco"
        assert output["location"]["country"] == "US"

    def test_convenience_function(self):
        candidate = _make_candidate()
        output = project(candidate)
        assert "full_name" in output or "name" in output
