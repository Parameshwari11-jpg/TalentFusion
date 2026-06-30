"""
validators.py — Pure validation functions for all data types.

All functions return (is_valid: bool, reason: str).
They NEVER raise exceptions — malformed input always results in
is_valid=False with an explanatory reason string.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def validate_email_address(email: str) -> tuple[bool, str]:
    """Validate an email address.

    Args:
        email: Email string to validate.

    Returns:
        (is_valid, reason).
    """
    if not email or not email.strip():
        return False, "Empty email string."
    try:
        validate_email(email.strip(), check_deliverability=False)
        return True, "Valid email."
    except EmailNotValidError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Unexpected validation error: {exc}"


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def validate_phone(phone: str, region: Optional[str] = None) -> tuple[bool, str]:
    """Validate a phone number.

    Args:
        phone:  Phone string to validate.
        region: Optional BCP-47 region hint (e.g. 'US', 'IN').

    Returns:
        (is_valid, reason).
    """
    if not phone or not phone.strip():
        return False, "Empty phone string."
    try:
        parsed = phonenumbers.parse(phone.strip(), region)
        if phonenumbers.is_valid_number(parsed):
            return True, "Valid phone number."
        return False, "Phone number is not valid for the given region."
    except phonenumbers.NumberParseException as exc:
        return False, f"Cannot parse phone: {exc}"
    except Exception as exc:
        return False, f"Unexpected phone validation error: {exc}"


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

_DATE_YYYY_MM = re.compile(r"^\d{4}-\d{2}$")
_PRESENT_VALUES = frozenset({"Present", "Current", "Now"})


def validate_date(date: str) -> tuple[bool, str]:
    """Validate a normalised date string (YYYY-MM or 'Present').

    Args:
        date: Date string to validate.

    Returns:
        (is_valid, reason).
    """
    if not date or not date.strip():
        return False, "Empty date string."
    if date.strip() in _PRESENT_VALUES:
        return True, "Present/Current indicator."
    if _DATE_YYYY_MM.match(date.strip()):
        year, month = date.split("-")
        if 1900 <= int(year) <= 2100 and 1 <= int(month) <= 12:
            return True, "Valid YYYY-MM date."
        return False, f"Date out of range: {date}"
    return False, f"Date '{date}' is not in YYYY-MM format."


# ---------------------------------------------------------------------------
# Country code
# ---------------------------------------------------------------------------

def validate_country_code(code: str) -> tuple[bool, str]:
    """Validate an ISO-3166 Alpha-2 country code.

    Args:
        code: Two-letter country code.

    Returns:
        (is_valid, reason).
    """
    if not code or not code.strip():
        return False, "Empty country code."
    try:
        import pycountry
        country = pycountry.countries.get(alpha_2=code.strip().upper())
        if country:
            return True, f"Valid ISO-3166 Alpha-2 code: {country.name}."
        return False, f"Unknown country code: '{code}'."
    except Exception as exc:
        return False, f"Country validation error: {exc}"


# ---------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------

def validate_url(url: str) -> tuple[bool, str]:
    """Validate a URL string.

    Args:
        url: URL to validate.

    Returns:
        (is_valid, reason).
    """
    if not url or not url.strip():
        return False, "Empty URL."
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return True, "Valid URL."
        return False, f"URL missing scheme or netloc: '{url}'."
    except Exception as exc:
        return False, f"URL parse error: {exc}"


# ---------------------------------------------------------------------------
# GitHub URL
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+$"
)


def validate_github_url(url: str) -> tuple[bool, str]:
    """Validate a GitHub profile URL.

    Args:
        url: GitHub URL to validate.

    Returns:
        (is_valid, reason).
    """
    if not url or not url.strip():
        return False, "Empty GitHub URL."
    cleaned = url.strip().rstrip("/")
    if _GITHUB_URL_RE.match(cleaned):
        return True, "Valid GitHub profile URL."
    return False, f"Not a valid GitHub profile URL: '{url}'."


# ---------------------------------------------------------------------------
# Experience entry
# ---------------------------------------------------------------------------

def validate_experience(entry: dict) -> tuple[bool, str]:
    """Validate an experience dict has the minimum required fields.

    Args:
        entry: Experience dict (company, title, etc.).

    Returns:
        (is_valid, reason).
    """
    if not isinstance(entry, dict):
        return False, f"Experience must be a dict, got {type(entry)}."
    if not entry.get("company") and not entry.get("title"):
        return False, "Experience entry must have at least 'company' or 'title'."
    return True, "Valid experience entry."


# ---------------------------------------------------------------------------
# Education entry
# ---------------------------------------------------------------------------

def validate_education(entry: dict) -> tuple[bool, str]:
    """Validate an education dict has the minimum required fields.

    Args:
        entry: Education dict.

    Returns:
        (is_valid, reason).
    """
    if not isinstance(entry, dict):
        return False, f"Education must be a dict, got {type(entry)}."
    if not entry.get("institution"):
        return False, "Education entry must have 'institution'."
    return True, "Valid education entry."
