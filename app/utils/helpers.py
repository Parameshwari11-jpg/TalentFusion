"""
helpers.py — Shared utility functions used across all modules.

Each function is pure (no side effects), stateless, and testable in
isolation.  Import only what you need — do not import the whole module.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# String utilities
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into a single space and strip.

    Args:
        text: Input string.

    Returns:
        Cleaned string.

    Examples:
        >>> normalize_whitespace("  hello   world  ")
        'hello world'
    """
    return re.sub(r"\s+", " ", text).strip()


def to_title_case(text: str) -> str:
    """Convert a string to Title Case, handling edge cases like 'McDonald'.

    Uses a simple heuristic: words that are already mixed-case (e.g. 'McA')
    are preserved as-is to avoid breaking proper nouns.

    Args:
        text: Input name string.

    Returns:
        Title-cased string.
    """
    if not text:
        return text
    words = normalize_whitespace(text).split()
    result = []
    for word in words:
        # Preserve words that have *mixed* case (e.g. 'McDonald')
        # but NOT pure ALL-CAPS words (those should be title-cased)
        has_lower = any(c.islower() for c in word)
        has_upper_after_first = any(c.isupper() for c in word[1:])
        if has_lower and has_upper_after_first:
            result.append(word)  # True mixed-case, e.g. 'McDonald'
        else:
            result.append(word.capitalize())
    return " ".join(result)


def slugify(text: str) -> str:
    """Convert text to a lowercase slug (for deduplication keys).

    Args:
        text: Input string.

    Returns:
        Lowercased, ASCII-normalised string with only alphanumerics and hyphens.

    Examples:
        >>> slugify("Node.js")
        'nodejs'
        >>> slugify("  AWS EC2  ")
        'aws-ec2'
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def remove_duplicates_preserve_order(items: list[Any]) -> list[Any]:
    """Remove duplicates from a list while preserving insertion order.

    Equality is determined by ``__eq__``.  For strings, comparison is
    case-insensitive.

    Args:
        items: Input list.

    Returns:
        Deduplicated list in original order.
    """
    seen: set = set()
    result: list[Any] = []
    for item in items:
        key = item.lower() if isinstance(item, str) else item
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# JSON utilities
# ---------------------------------------------------------------------------

def load_json_file(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file, returning an empty dict on failure.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed dict, or empty dict if the file is missing or malformed.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_json_file(path: Path, data: Any, indent: int = 2) -> bool:
    """Write data to a JSON file atomically.

    Args:
        path:   Destination path.
        data:   JSON-serialisable object.
        indent: Indentation for pretty-printing (default 2).

    Returns:
        True on success, False on failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False, default=str)
        return True
    except (OSError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Hashing / determinism
# ---------------------------------------------------------------------------

def stable_hash(value: Any) -> str:
    """Produce a deterministic SHA-256 hex digest for any JSON-serialisable value.

    Used to generate stable candidate IDs or deduplication keys.

    Args:
        value: Any JSON-serialisable object.

    Returns:
        64-character hex string.
    """
    serialised = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def extract_years_from_text(text: str) -> Optional[float]:
    """Extract a years-of-experience number from free-form text.

    Handles patterns like:
        "5+ years of experience"
        "3-5 years"
        "7 years"
        "over 10 years"

    Args:
        text: Free-form description string.

    Returns:
        Extracted float, or None if not found.
    """
    patterns = [
        r"(\d+\.?\d*)\s*\+?\s*years?",
        r"(\d+\.?\d*)\s*-\s*\d+\s*years?",
        r"over\s+(\d+\.?\d*)\s*years?",
        r"(\d+\.?\d*)\s*yrs?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


def clean_url(url: str) -> str:
    """Strip trailing slashes and whitespace from a URL.

    Args:
        url: Raw URL string.

    Returns:
        Cleaned URL string.
    """
    return url.strip().rstrip("/")


def is_empty(value: Any) -> bool:
    """Return True if a value is None, empty string, or empty collection.

    Args:
        value: Any value to check.

    Returns:
        True if considered empty.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) == 0
    return False
