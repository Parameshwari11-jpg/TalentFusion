"""
test_parsers.py — Unit tests for ATS, GitHub, and Resume parsers.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers.ats_parser import ATSParser, parse_ats
from app.parsers.github_parser import GitHubParser
from app.models.confidence import SourceType


# ---------------------------------------------------------------------------
# ATS Parser
# ---------------------------------------------------------------------------
class TestATSParser:
    def test_parse_canonical_field_names(self):
        raw = {
            "full_name": "Jane Smith",
            "email": "jane@example.com",
            "skills": ["Python", "Docker"],
        }
        result = parse_ats(raw)
        assert result.available is True
        assert result.source_type == SourceType.ATS
        assert "full_name" in result.fields
        assert result.fields["full_name"].value == "Jane Smith"

    def test_parse_camel_case_aliases(self):
        raw = {
            "candidateName": "John Doe",
            "emailAddress": "john@example.com",
            "technical_skills": ["JS", "React"],
        }
        result = parse_ats(raw)
        assert "full_name" in result.fields
        assert result.fields["full_name"].value == "John Doe"
        assert "skills" in result.list_fields
        assert len(result.list_fields["skills"]) == 2

    def test_parse_experience_list(self):
        raw = {
            "name": "Test User",
            "work_experience": [
                {
                    "company": "Google",
                    "title": "SWE",
                    "start_date": "2021-01",
                    "end_date": "Present",
                }
            ],
        }
        result = parse_ats(raw)
        assert "experience" in result.list_fields
        assert len(result.list_fields["experience"]) == 1

    def test_parse_education_list(self):
        raw = {
            "name": "Test User",
            "education": [
                {
                    "school": "MIT",
                    "degree": "BS",
                    "major": "CS",
                }
            ],
        }
        result = parse_ats(raw)
        assert "education" in result.list_fields

    def test_parse_empty_ats(self):
        result = parse_ats({})
        assert result.available is True
        assert len(result.fields) == 0

    def test_parse_broken_ats_does_not_crash(self):
        result = parse_ats({"skills": "not a list or string that can be parsed fine"})
        assert result.available is True

    def test_links_extracted(self):
        raw = {
            "name": "Test",
            "linkedin_url": "https://linkedin.com/in/test",
            "github_url": "https://github.com/test",
        }
        result = parse_ats(raw)
        assert "links" in result.fields
        links_value = result.fields["links"].value
        assert "linkedin" in links_value

    def test_source_type_is_ats(self):
        result = parse_ats({"name": "Test"})
        assert result.source_type == SourceType.ATS

    def test_raw_field_confidence(self):
        result = parse_ats({"name": "Test"})
        rf = result.fields["full_name"]
        assert rf.confidence == 0.95

    def test_comma_separated_skills(self):
        raw = {"skills": "Python, JavaScript, Docker"}
        result = parse_ats(raw)
        assert "skills" in result.list_fields
        assert len(result.list_fields["skills"]) == 3


# ---------------------------------------------------------------------------
# GitHub Parser (mocked API)
# ---------------------------------------------------------------------------
class TestGitHubParser:
    def _make_parser(self) -> GitHubParser:
        return GitHubParser(token=None)

    def test_extract_username_standard_url(self):
        parser = self._make_parser()
        assert parser._extract_username("https://github.com/torvalds") == "torvalds"

    def test_extract_username_trailing_slash(self):
        parser = self._make_parser()
        assert parser._extract_username("https://github.com/torvalds/") == "torvalds"

    def test_extract_username_no_https(self):
        parser = self._make_parser()
        assert parser._extract_username("github.com/torvalds") == "torvalds"

    def test_extract_username_invalid(self):
        parser = self._make_parser()
        assert parser._extract_username("https://notgithub.com/user") is None

    def test_parse_invalid_url(self):
        parser = self._make_parser()
        result = parser.parse("not-a-url")
        assert result.available is False
        assert len(result.parse_errors) > 0

    @patch("app.parsers.github_parser.requests.Session.get")
    def test_parse_user_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        parser = self._make_parser()
        result = parser.parse("https://github.com/nonexistentuser123456")
        assert result.available is False

    @patch("app.parsers.github_parser.requests.Session.get")
    def test_parse_successful_user(self, mock_get):
        user_resp = MagicMock()
        user_resp.status_code = 200
        user_resp.json.return_value = {
            "name": "Linus Torvalds",
            "bio": "Creator of Linux",
            "email": None,
            "location": "Portland, OR, US",
            "blog": "https://torvalds.github.io",
            "html_url": "https://github.com/torvalds",
        }
        repos_resp = MagicMock()
        repos_resp.status_code = 200
        repos_resp.json.return_value = [
            {"language": "C"},
            {"language": "Python"},
            {"language": "C"},
        ]
        mock_get.side_effect = [user_resp, repos_resp]

        parser = self._make_parser()
        result = parser.parse("https://github.com/torvalds")
        assert result.available is True
        assert "full_name" in result.fields
        assert result.fields["full_name"].value == "Linus Torvalds"
        assert "skills" in result.list_fields
        # C should appear (2 repos), Python (1 repo)
        skill_values = [rf.value for rf in result.list_fields["skills"]]
        assert "C" in skill_values
