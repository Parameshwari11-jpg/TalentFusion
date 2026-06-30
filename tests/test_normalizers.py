"""
test_normalizers.py — Unit tests for all normalizer modules.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.normalizers.phone_normalizer import normalize_phone
from app.normalizers.date_normalizer import normalize_date
from app.normalizers.skill_normalizer import normalize_skill
from app.normalizers.location_normalizer import normalize_location
from app.normalizers.email_normalizer import normalize_email
from app.normalizers.name_normalizer import normalize_name
from config.settings import CONFIDENCE_INVALID_DATA


# ---------------------------------------------------------------------------
# Phone normalizer
# ---------------------------------------------------------------------------
class TestPhoneNormalizer:
    def test_e164_us_number(self):
        phone, conf = normalize_phone("+1-650-555-0192")
        assert phone == "+16505550192"
        assert conf == 1.0

    def test_local_number_with_country_hint(self):
        phone, conf = normalize_phone("9876543210", country_hint="IN")
        assert phone.startswith("+91")
        assert conf == 1.0

    def test_invalid_number_kept(self):
        raw = "not-a-phone"
        phone, conf = normalize_phone(raw)
        assert phone == raw
        assert conf == CONFIDENCE_INVALID_DATA

    def test_empty_string(self):
        phone, conf = normalize_phone("")
        assert conf == CONFIDENCE_INVALID_DATA

    def test_international_number(self):
        phone, conf = normalize_phone("+44 20 7946 0958")
        assert phone.startswith("+44")
        assert conf == 1.0


# ---------------------------------------------------------------------------
# Date normalizer
# ---------------------------------------------------------------------------
class TestDateNormalizer:
    def test_month_year_word(self):
        result, ok = normalize_date("January 2024")
        assert result == "2024-01"
        assert ok is True

    def test_month_abbrev(self):
        result, ok = normalize_date("Jan 2024")
        assert result == "2024-01"
        assert ok is True

    def test_mm_yyyy_slash(self):
        result, ok = normalize_date("01/2024")
        assert result == "2024-01"
        assert ok is True

    def test_already_normalised(self):
        result, ok = normalize_date("2024-01")
        assert result == "2024-01"
        assert ok is True

    def test_present(self):
        result, ok = normalize_date("Present")
        assert result == "Present"
        assert ok is True

    def test_current(self):
        result, ok = normalize_date("current")
        assert result == "Present"
        assert ok is True

    def test_full_iso_date(self):
        result, ok = normalize_date("2024-01-15")
        assert result == "2024-01"
        assert ok is True

    def test_plain_year(self):
        result, ok = normalize_date("2019")
        assert result == "2019-01"
        assert ok is True

    def test_empty_string(self):
        result, ok = normalize_date("")
        assert ok is False


# ---------------------------------------------------------------------------
# Skill normalizer
# ---------------------------------------------------------------------------
class TestSkillNormalizer:
    def test_js_alias(self):
        name, was_canon, method = normalize_skill("JS")
        assert name == "JavaScript"
        assert was_canon is True
        assert method == "exact"

    def test_python3(self):
        name, was_canon, _ = normalize_skill("python3")
        assert name == "Python"
        assert was_canon is True

    def test_nodejs(self):
        name, was_canon, _ = normalize_skill("node")
        assert name == "Node.js"

    def test_reactjs(self):
        name, was_canon, _ = normalize_skill("React.js")
        assert name == "React"

    def test_unknown_skill_passthrough(self):
        name, was_canon, method = normalize_skill("QuantumML")
        assert method == "passthrough"

    def test_case_insensitive(self):
        name, was_canon, _ = normalize_skill("JAVASCRIPT")
        assert name == "JavaScript"

    def test_empty_string(self):
        name, was_canon, method = normalize_skill("")
        assert method == "passthrough"


# ---------------------------------------------------------------------------
# Location normalizer
# ---------------------------------------------------------------------------
class TestLocationNormalizer:
    def test_full_location(self):
        loc = normalize_location("San Francisco, CA, United States")
        assert loc.city == "San Francisco"
        assert loc.country == "US"

    def test_india(self):
        loc = normalize_location("Bangalore, India")
        assert loc.country == "IN"

    def test_uk_alias(self):
        loc = normalize_location("London, UK")
        assert loc.country == "GB"

    def test_alpha2_passthrough(self):
        loc = normalize_location("Berlin, DE")
        assert loc.country == "DE"

    def test_empty_string(self):
        loc = normalize_location("")
        assert loc.city is None
        assert loc.country is None

    def test_dict_location(self):
        loc = normalize_location({
            "city": "Coimbatore",
            "state": "Tamil Nadu",
            "postal_code": "640132",
            "country": "IN"
        })
        assert loc.city == "Coimbatore"
        assert loc.state == "Tamil Nadu"
        assert loc.country == "IN"
        assert "Coimbatore" in loc.raw

    def test_stringified_dict_location(self):
        loc = normalize_location("{'city': 'Coimbatore', 'state': 'Tamil Nadu', 'postal_code': '640132', 'country': 'IN'}")
        assert loc.city == "Coimbatore"
        assert loc.state == "Tamil Nadu"
        assert loc.country == "IN"
        assert "Coimbatore" in loc.raw


# ---------------------------------------------------------------------------
# Email normalizer
# ---------------------------------------------------------------------------
class TestEmailNormalizer:
    def test_valid_email(self):
        email, is_valid, conf = normalize_email("Test@Example.COM")
        assert is_valid is True
        assert email == "test@example.com"
        assert conf == 1.0

    def test_invalid_email_kept(self):
        raw = "not-an-email"
        email, is_valid, conf = normalize_email(raw)
        assert is_valid is False
        assert email == raw
        assert conf == CONFIDENCE_INVALID_DATA

    def test_empty_string(self):
        _, is_valid, conf = normalize_email("")
        assert is_valid is False
        assert conf == CONFIDENCE_INVALID_DATA

    def test_email_with_plus(self):
        email, is_valid, _ = normalize_email("user+tag@example.com")
        assert is_valid is True

    def test_ocr_corrected_email(self):
        email, is_valid, conf = normalize_email("paramesh.ravill@gmail.ccom")
        assert is_valid is True
        assert email == "paramesh.ravi11@gmail.com"
        assert conf == 1.0


# ---------------------------------------------------------------------------
# Name normalizer
# ---------------------------------------------------------------------------
class TestNameNormalizer:
    def test_lowercase_name(self):
        name, is_valid = normalize_name("john doe")
        assert name == "John Doe"
        assert is_valid is True

    def test_uppercase_name(self):
        name, is_valid = normalize_name("JANE SMITH")
        assert name == "Jane Smith"
        assert is_valid is True

    def test_extra_whitespace(self):
        name, is_valid = normalize_name("  alice   wonderland  ")
        assert name == "Alice Wonderland"
        assert is_valid is True

    def test_mixed_case_preserved(self):
        name, is_valid = normalize_name("McDonald")
        assert "Mc" in name or "mc" in name.lower()

    def test_empty_string(self):
        name, is_valid = normalize_name("")
        assert is_valid is False

    def test_too_short(self):
        name, is_valid = normalize_name("A")
        assert is_valid is False
