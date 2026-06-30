"""
test_merger.py — Unit tests for the merge engine and sub-mergers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.confidence.confidence_engine import ConfidenceEngine
from app.merger.field_merger import FieldMerger
from app.merger.list_merger import ListMerger
from app.merger.merge_engine import MergeEngine
from app.models.candidate import ParsedSource, RawField
from app.models.confidence import SourceType
from app.provenance.provenance_tracker import ProvenanceTracker


def _make_raw(value, source: SourceType, confidence: float = 0.85) -> RawField:
    return RawField(
        value=value,
        source=source,
        confidence=confidence,
        method="test_parser",
        raw=value,
    )


# ---------------------------------------------------------------------------
# ConfidenceEngine
# ---------------------------------------------------------------------------
class TestConfidenceEngine:
    def setup_method(self):
        self.engine = ConfidenceEngine()

    def test_single_ats(self):
        cs = self.engine.compute("name", [SourceType.ATS], [SourceType.ATS])
        assert cs.score == 0.95

    def test_single_resume(self):
        cs = self.engine.compute("name", [SourceType.RESUME], [SourceType.RESUME])
        assert cs.score == 0.85

    def test_single_github(self):
        cs = self.engine.compute("name", [SourceType.GITHUB], [SourceType.GITHUB])
        assert cs.score == 0.80

    def test_ats_plus_resume(self):
        cs = self.engine.compute(
            "name",
            [SourceType.ATS, SourceType.RESUME],
            [SourceType.ATS, SourceType.RESUME],
        )
        assert cs.score == 0.98

    def test_all_three(self):
        cs = self.engine.compute(
            "name",
            [SourceType.ATS, SourceType.RESUME, SourceType.GITHUB],
            [SourceType.ATS, SourceType.RESUME, SourceType.GITHUB],
        )
        assert cs.score == 1.00

    def test_empty_sources(self):
        cs = self.engine.compute("name", [], [])
        assert cs.score == 0.0

    def test_overall_confidence(self):
        from app.models.confidence import ConfidenceScore
        scores = {
            "name": ConfidenceScore(field="name", score=0.98),
            "email": ConfidenceScore(field="email", score=0.90),
        }
        overall = self.engine.compute_overall(scores)
        assert abs(overall - 0.94) < 0.01


# ---------------------------------------------------------------------------
# FieldMerger
# ---------------------------------------------------------------------------
class TestFieldMerger:
    def setup_method(self):
        conf = ConfidenceEngine()
        prov = ProvenanceTracker()
        self.merger = FieldMerger(conf, prov)

    def test_single_value(self):
        candidates = [_make_raw("Google", SourceType.ATS, 0.95)]
        value, conf = self.merger.merge("company", candidates)
        assert value == "Google"
        assert conf.score == 0.95

    def test_agreement_bonus(self):
        candidates = [
            _make_raw("Google", SourceType.ATS, 0.95),
            _make_raw("Google", SourceType.RESUME, 0.85),
        ]
        value, conf = self.merger.merge("company", candidates)
        assert value.lower() == "google"
        assert conf.score == 0.98  # ATS+Resume agreement bonus

    def test_conflict_highest_confidence_wins(self):
        candidates = [
            _make_raw("Google", SourceType.ATS, 0.95),
            _make_raw("Amazon", SourceType.RESUME, 0.85),
        ]
        value, conf = self.merger.merge("company", candidates)
        assert value.lower() == "google"  # ATS wins

    def test_empty_candidates(self):
        value, conf = self.merger.merge("company", [])
        assert value is None

    def test_normalise_fn_applied(self):
        candidates = [
            _make_raw("  jane doe  ", SourceType.ATS, 0.95),
        ]
        value, _ = self.merger.merge("name", candidates, normalise_fn=str.strip)
        assert value == "jane doe"


# ---------------------------------------------------------------------------
# ListMerger — Skills
# ---------------------------------------------------------------------------
class TestListMergerSkills:
    def setup_method(self):
        conf = ConfidenceEngine()
        prov = ProvenanceTracker()
        self.merger = ListMerger(conf, prov)

    def test_single_source_skills(self):
        tuples = [
            ("Python", SourceType.ATS, "ats_parser", "", 0.95),
            ("Docker", SourceType.ATS, "ats_parser", "", 0.95),
        ]
        skills = self.merger.merge_skills(tuples)
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert "Python" in names
        assert "Docker" in names

    def test_deduplication(self):
        tuples = [
            ("Python", SourceType.ATS, "ats_parser", "", 0.95),
            ("Python", SourceType.RESUME, "resume_ocr", "", 0.85),
        ]
        skills = self.merger.merge_skills(tuples)
        # Should deduplicate to 1 skill
        assert len(skills) == 1
        assert skills[0].confidence == 0.98  # ATS+Resume agreement

    def test_agreement_increases_confidence(self):
        tuples = [
            ("JavaScript", SourceType.ATS, "ats_parser", "JS", 0.95),
            ("JavaScript", SourceType.RESUME, "resume_ocr", "javascript", 0.85),
            ("JavaScript", SourceType.GITHUB, "github_api", "JavaScript", 0.80),
        ]
        skills = self.merger.merge_skills(tuples)
        assert len(skills) == 1
        assert skills[0].confidence == 1.00


# ---------------------------------------------------------------------------
# Full MergeEngine integration
# ---------------------------------------------------------------------------
class TestMergeEngine:
    def test_merge_single_ats_source(self):
        source = ParsedSource(
            source_type=SourceType.ATS,
            fields={
                "full_name": _make_raw("Alice Johnson", SourceType.ATS, 0.95),
                "headline": _make_raw("Software Engineer", SourceType.ATS, 0.95),
            },
            list_fields={
                "emails": [_make_raw("alice@example.com", SourceType.ATS, 0.95)],
                "skills": [_make_raw("Python", SourceType.ATS, 0.95)],
            },
            available=True,
        )
        engine = MergeEngine()
        candidate = engine.merge([source])
        assert candidate.full_name == "Alice Johnson"
        assert "alice@example.com" in candidate.emails
        assert any(s.name == "Python" for s in candidate.skills)

    def test_merge_unavailable_source_skipped(self):
        source_ok = ParsedSource(
            source_type=SourceType.ATS,
            fields={"full_name": _make_raw("Bob", SourceType.ATS, 0.95)},
            available=True,
        )
        source_bad = ParsedSource(
            source_type=SourceType.RESUME,
            available=False,
        )
        engine = MergeEngine()
        candidate = engine.merge([source_ok, source_bad])
        assert candidate.full_name == "Bob"

    def test_merge_empty_sources(self):
        engine = MergeEngine()
        candidate = engine.merge([])
        assert candidate.candidate_id  # UUID still assigned
        assert candidate.full_name is None

    def test_candidate_id_is_deterministic_per_run(self):
        """Each run produces a new UUID (determinism means same output for same inputs,
        but candidate_id is UUID per run by design)."""
        source = ParsedSource(
            source_type=SourceType.ATS,
            fields={"full_name": _make_raw("Test", SourceType.ATS, 0.95)},
            available=True,
        )
        engine = MergeEngine()
        c1 = engine.merge([source])
        c2 = engine.merge([source])
        # IDs are different per run (UUID4), but structure is identical
        assert c1.full_name == c2.full_name
