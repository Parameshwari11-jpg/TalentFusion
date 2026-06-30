"""
settings.py — Application-wide constants and configuration.

All confidence values, source identifiers, and tunable parameters
live here. No other module should hardcode these values.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR: Path = Path(__file__).resolve().parent.parent
CONFIG_DIR: Path = ROOT_DIR / "config"
OUTPUT_DIR: Path = ROOT_DIR / "output"
SAMPLE_DIR: Path = ROOT_DIR / "sample_inputs"
MERGE_LOG_PATH: Path = ROOT_DIR / "merge_log.json"

# ---------------------------------------------------------------------------
# Source identifiers (canonical strings used throughout the codebase)
# ---------------------------------------------------------------------------
SOURCE_ATS: str = "ATS"
SOURCE_RESUME: str = "Resume"
SOURCE_GITHUB: str = "GitHub"

# ---------------------------------------------------------------------------
# Parser method identifiers
# ---------------------------------------------------------------------------
METHOD_ATS_PARSER: str = "ats_parser"
METHOD_RESUME_OCR: str = "resume_ocr"
METHOD_GITHUB_API: str = "github_api"

# ---------------------------------------------------------------------------
# Base source confidence scores
# These represent how reliable each source is considered, in isolation.
# ---------------------------------------------------------------------------
CONFIDENCE_ATS_BASE: float = 0.95
CONFIDENCE_RESUME_BASE: float = 0.85
CONFIDENCE_GITHUB_BASE: float = 0.80
CONFIDENCE_INVALID_DATA: float = 0.20

# ---------------------------------------------------------------------------
# Agreement bonus scores
# Applied when multiple sources agree on the same normalized value.
# Keys are frozensets of source names.
# ---------------------------------------------------------------------------
CONFIDENCE_AGREEMENT: dict[str, float] = {
    "ATS": 0.95,
    "Resume": 0.85,
    "GitHub": 0.80,
    "ATS+Resume": 0.98,
    "ATS+GitHub": 0.97,
    "Resume+GitHub": 0.93,
    "ATS+Resume+GitHub": 1.00,
}

# ---------------------------------------------------------------------------
# Missing field policies (used by the projection engine)
# ---------------------------------------------------------------------------
POLICY_NULL: str = "null"
POLICY_OMIT: str = "omit"
POLICY_ERROR: str = "error"

VALID_MISSING_POLICIES: set[str] = {POLICY_NULL, POLICY_OMIT, POLICY_ERROR}

# ---------------------------------------------------------------------------
# Fuzzy matching threshold for skill canonicalization (0–100, RapidFuzz)
# ---------------------------------------------------------------------------
SKILL_FUZZY_THRESHOLD: int = 82

# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------
GITHUB_API_BASE: str = "https://api.github.com"
GITHUB_REQUEST_TIMEOUT: int = 15   # seconds
GITHUB_MAX_REPOS: int = 100        # max repos to fetch for language inference

# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
# 150 DPI is sufficient for clean single-page resumes and is ~4x faster than
# 300 DPI (image area scales as DPI²). Increase to 200–300 only for very
# degraded/hand-written scans.
OCR_DPI: int = 150                 # DPI for pdf2image conversion
OCR_LANG: str = "eng"             # Tesseract language

# ---------------------------------------------------------------------------
# Date normalization output format
# ---------------------------------------------------------------------------
DATE_OUTPUT_FORMAT: str = "%Y-%m"

# ---------------------------------------------------------------------------
# Canonical field names (used as dictionary keys throughout)
# ---------------------------------------------------------------------------
FIELD_FULL_NAME: str = "full_name"
FIELD_EMAILS: str = "emails"
FIELD_PHONES: str = "phones"
FIELD_LOCATION: str = "location"
FIELD_LINKS: str = "links"
FIELD_HEADLINE: str = "headline"
FIELD_YEARS_EXP: str = "years_experience"
FIELD_SKILLS: str = "skills"
FIELD_EXPERIENCE: str = "experience"
FIELD_EDUCATION: str = "education"
FIELD_PROVENANCE: str = "provenance"
FIELD_OVERALL_CONFIDENCE: str = "overall_confidence"

ALL_CANONICAL_FIELDS: list[str] = [
    FIELD_FULL_NAME,
    FIELD_EMAILS,
    FIELD_PHONES,
    FIELD_LOCATION,
    FIELD_LINKS,
    FIELD_HEADLINE,
    FIELD_YEARS_EXP,
    FIELD_SKILLS,
    FIELD_EXPERIENCE,
    FIELD_EDUCATION,
    FIELD_PROVENANCE,
    FIELD_OVERALL_CONFIDENCE,
]
