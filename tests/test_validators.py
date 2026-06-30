"""
test_validators.py — Unit tests for all validators.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.validators.validators import (
    validate_email_address,
    validate_phone,
    validate_date,
    validate_country_code,
    validate_url,
    validate_github_url,
    validate_experience,
    validate_education,
)


class TestEmailValidator:
    def test_valid_email(self):
        ok, _ = validate_email_address("user@example.com")
        assert ok is True

    def test_invalid_email(self):
        ok, reason = validate_email_address("not-an-email")
        assert ok is False
        assert reason

    def test_empty_email(self):
        ok, _ = validate_email_address("")
        assert ok is False


class TestPhoneValidator:
    def test_valid_international(self):
        ok, _ = validate_phone("+16505550192")
        assert ok is True

    def test_valid_with_region(self):
        ok, _ = validate_phone("9876543210", region="IN")
        assert ok is True

    def test_invalid_phone(self):
        ok, reason = validate_phone("not-a-phone")
        assert ok is False

    def test_empty_phone(self):
        ok, _ = validate_phone("")
        assert ok is False


class TestDateValidator:
    def test_valid_yyyy_mm(self):
        ok, _ = validate_date("2024-01")
        assert ok is True

    def test_present(self):
        ok, _ = validate_date("Present")
        assert ok is True

    def test_invalid_format(self):
        ok, _ = validate_date("Jan 2024")  # Not normalised yet
        assert ok is False

    def test_empty_date(self):
        ok, _ = validate_date("")
        assert ok is False

    def test_out_of_range_month(self):
        ok, _ = validate_date("2024-13")
        assert ok is False


class TestCountryValidator:
    def test_valid_us(self):
        ok, _ = validate_country_code("US")
        assert ok is True

    def test_valid_in(self):
        ok, _ = validate_country_code("IN")
        assert ok is True

    def test_invalid_code(self):
        ok, _ = validate_country_code("ZZ")
        assert ok is False

    def test_empty_code(self):
        ok, _ = validate_country_code("")
        assert ok is False


class TestURLValidator:
    def test_valid_https(self):
        ok, _ = validate_url("https://example.com")
        assert ok is True

    def test_valid_http(self):
        ok, _ = validate_url("http://example.com/path")
        assert ok is True

    def test_no_scheme(self):
        ok, _ = validate_url("example.com")
        assert ok is False

    def test_empty_url(self):
        ok, _ = validate_url("")
        assert ok is False


class TestGitHubURLValidator:
    def test_valid_github_url(self):
        ok, _ = validate_github_url("https://github.com/torvalds")
        assert ok is True

    def test_trailing_slash_ok(self):
        ok, _ = validate_github_url("https://github.com/torvalds/")
        assert ok is True

    def test_repo_url_invalid(self):
        ok, _ = validate_github_url("https://github.com/user/repo")
        assert ok is False

    def test_empty_url(self):
        ok, _ = validate_github_url("")
        assert ok is False


class TestExperienceValidator:
    def test_valid_experience(self):
        ok, _ = validate_experience({"company": "Google", "title": "SWE"})
        assert ok is True

    def test_missing_both_fields(self):
        ok, _ = validate_experience({})
        assert ok is False

    def test_not_a_dict(self):
        ok, _ = validate_experience("not a dict")
        assert ok is False


class TestEducationValidator:
    def test_valid_education(self):
        ok, _ = validate_education({"institution": "MIT"})
        assert ok is True

    def test_missing_institution(self):
        ok, _ = validate_education({"degree": "BS"})
        assert ok is False

    def test_not_a_dict(self):
        ok, _ = validate_education(42)
        assert ok is False
