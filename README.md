# Multi-Source Candidate Data Transformer

> **EightFold AI — Internship Assignment**  
> A production-quality Python pipeline that ingests candidate data from three heterogeneous sources and produces a single, trusted canonical profile.

---

## 📋 Table of Contents
- [Architecture](#architecture)
- [Folder Structure](#folder-structure)
- [Installation](#installation)
- [Execution](#execution)
- [Configuration](#configuration)
- [Design Decisions](#design-decisions)
- [Assumptions](#assumptions)
- [Future Improvements](#future-improvements)
- [Testing](#testing)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                              │
│   ATS JSON │  Resume PDF (scanned/image)  │  GitHub URL        │
└─────┬───────────────────┬──────────────────────────┬────────────┘
      ▼                   ▼                          ▼
 ATSParser         ResumeParser              GitHubParser
 (field-alias      (OCR pipeline:            (REST API:
  resolution)       pdf2image→CV2→            /users + /repos)
                    pytesseract)
      │                   │                          │
      └───────────────────┴──────────────────────────┘
                          │
                    ParsedSource ×3
                    (RawField[T] tagged values)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
         Normalizer Layer         MergeEngine
         (phone→E.164,            ├── FieldMerger (scalar)
          date→YYYY-MM,           ├── ListMerger (lists)
          skill→canonical,        ├── ConfidenceEngine
          location→ISO-3166,      └── ProvenanceTracker
          email validate,
          name title-case)
                          │
                  CanonicalCandidate
                  (Pydantic, source-independent)
                          │
                  ProjectionEngine
                  (config-driven output shaping)
                          │
                    Output JSON
                    (Streamlit UI / Download)
```

### Confidence Model

| Agreement | Confidence |
|-----------|-----------|
| ATS only | 0.95 |
| Resume only | 0.85 |
| GitHub only | 0.80 |
| ATS + Resume | 0.98 |
| ATS + GitHub | 0.97 |
| Resume + GitHub | 0.93 |
| All three agree | 1.00 |
| Invalid data | 0.20 |

---

## Folder Structure

```
EightFoldAI/
├── app/
│   ├── models/
│   │   ├── candidate.py        # RawField, ParsedSource, CanonicalCandidate, etc.
│   │   ├── confidence.py       # SourceType enum, agreement table, helpers
│   │   └── provenance.py       # ProvenanceRecord model
│   ├── parsers/
│   │   ├── ats_parser.py       # ATS JSON → ParsedSource (alias-driven)
│   │   ├── resume_parser.py    # PDF OCR → ParsedSource (pdf2image+CV2+tesseract)
│   │   └── github_parser.py    # GitHub REST API → ParsedSource
│   ├── normalizers/
│   │   ├── phone_normalizer.py # E.164 via phonenumbers
│   │   ├── date_normalizer.py  # YYYY-MM via dateparser + regex
│   │   ├── skill_normalizer.py # Canonical skills via alias map + RapidFuzz
│   │   ├── location_normalizer.py # ISO-3166 α-2 via pycountry
│   │   ├── email_normalizer.py # RFC validation via email-validator
│   │   └── name_normalizer.py  # Title case, whitespace, noise removal
│   ├── merger/
│   │   ├── field_merger.py     # Scalar conflict resolution
│   │   ├── list_merger.py      # Dedup+merge for skills/emails/phones/exp/edu
│   │   └── merge_engine.py     # Full pipeline orchestrator
│   ├── confidence/
│   │   └── confidence_engine.py # Agreement-bonus computation
│   ├── provenance/
│   │   └── provenance_tracker.py # Provenance record accumulation
│   ├── projection/
│   │   └── projection_engine.py  # Config-driven output shaping
│   ├── validators/
│   │   └── validators.py       # Pure validator functions
│   ├── services/
│   │   └── transformer_service.py # End-to-end orchestration
│   └── utils/
│       ├── logger.py           # Structured logger factory
│       └── helpers.py          # Pure utility functions
├── ui/
│   └── streamlit_app.py        # Streamlit UI (5 tabs)
├── config/
│   ├── settings.py             # All constants (confidence values, paths)
│   ├── ats_field_map.json      # ATS vendor alias map
│   ├── skill_aliases.json      # Canonical skill alias map
│   └── output_config.json      # Default projection config
├── sample_inputs/
│   ├── sample_ats.json
│   └── sample_output_config.json
├── output/                     # Generated profiles saved here
├── tests/
│   ├── test_normalizers.py     # 30+ normalizer tests
│   ├── test_parsers.py         # 20+ parser tests (GitHub mocked)
│   ├── test_merger.py          # 20+ merge engine tests
│   ├── test_projection.py      # 12 projection tests
│   └── test_validators.py      # 25 validator tests
├── docs/
│   └── design_document.md
├── merge_log.json              # Written on every pipeline run
├── requirements.txt
└── README.md
```

---

## Installation

### Prerequisites

1. **Python 3.11+**

2. **Tesseract OCR** (required for scanned PDF parsing):
   - **Windows**: Download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and install. Add to PATH or set `tesseract_cmd` in the service.
   - **Linux/Mac**: `sudo apt-get install tesseract-ocr` / `brew install tesseract`

3. **Poppler** (required for pdf2image on Windows):
   - **Windows**: Download from [oschwartz10612/poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases), extract, add `bin/` to PATH.
   - **Linux**: `sudo apt-get install poppler-utils`
   - **Mac**: `brew install poppler`

### Install Python dependencies

```bash
pip install -r requirements.txt
```

### Optional: GitHub API token (recommended)

Without a token, the GitHub API allows 60 requests/hour. With a token, it allows 5000.

Create a `.env` file in the project root:

```env
GITHUB_TOKEN=ghp_your_personal_access_token_here
```

---

## Execution

### Streamlit UI (recommended)

```bash
streamlit run ui/streamlit_app.py
```

Then open `http://localhost:8501` in your browser.

**Upload your data in the sidebar:**
1. ATS JSON file
2. Resume PDF (scanned/image-based)
3. GitHub profile URL
4. (Optional) Custom output config JSON

Click **Generate Profile** to run the pipeline.

### Run tests

```bash
python -m pytest tests/ -v
```

### Programmatic usage

```python
from app.services.transformer_service import TransformerService

service = TransformerService()
canonical, projected, errors = service.transform(
    ats_data={"name": "John Doe", "skills": ["Python", "Docker"]},
    github_url="https://github.com/johndoe",
)
print(canonical.full_name)   # "John Doe"
print(projected)             # Final output dict
```

---

## Configuration

### ATS Field Alias Map (`config/ats_field_map.json`)

Maps any ATS vendor's field names to canonical keys. Add new aliases without touching code:

```json
{
  "name_mappings": {
    "full_name": ["name", "candidateName", "applicant_name", ...]
  }
}
```

### Skill Aliases (`config/skill_aliases.json`)

Maps raw skill strings to canonical names. RapidFuzz fuzzy matching handles unlisted aliases:

```json
{
  "JavaScript": ["js", "java script", "ecmascript", "es6", ...],
  "Python": ["py", "python3", "python 2", ...]
}
```

### Output Projection Config

Control exactly what appears in the output JSON:

```json
{
  "fields": ["full_name", "emails", "skills"],
  "rename": {"full_name": "name"},
  "include_confidence": true,
  "include_provenance": false,
  "missing_field_policy": "null"
}
```

`missing_field_policy` options: `"null"` (include null), `"omit"` (skip field), `"error"` (raise exception).

---

## Design Decisions

### 1. `RawField[T]` Generic Wrapper
Every parsed value is wrapped as `RawField(value, source, confidence, method, raw)` before merging. This makes the merge engine completely source-agnostic — it operates only on `RawField` objects regardless of which parser produced them.

### 2. Canonical Model Independence
The `CanonicalCandidate` Pydantic model is built first, 100% independently of any output configuration. The `ProjectionEngine` then reads a JSON config to shape the final output. This means output formats can change without touching any business logic.

### 3. Determinism
All merging uses sorted, stable comparisons. No randomness. Tie-breaking is by source priority (ATS > Resume > GitHub). Same inputs → same outputs.

### 4. Graceful Degradation
Every parser is wrapped in try/except. An OCR failure produces `ParsedSource(available=False)`, which the merge engine skips. The pipeline always produces a result, even with 0 working sources.

### 5. Data-Driven ATS Parsing
ATS field name resolution is entirely driven by `ats_field_map.json`. No code changes are needed to support a new ATS vendor — just add aliases to the JSON file.

### 6. Two-Stage Skill Canonicalization
Stage 1: Exact alias lookup (fast, O(1)). Stage 2: RapidFuzz token-sort-ratio fuzzy matching (handles typos and word-order variations). Threshold is configurable via `SKILL_FUZZY_THRESHOLD`.

### 7. pdfplumber Fast-Path + OCR Fallback
The resume parser first attempts pdfplumber (for text-based PDFs). If insufficient text is extracted (< 100 chars), it falls back to the full OCR pipeline (pdf2image → OpenCV preprocessing → pytesseract).

### 8. Centralized Constants
All confidence values (0.95, 0.98, 1.00, etc.) are defined exactly once in `config/settings.py` and `app/models/confidence.py`. Nothing is hardcoded inline.

---

## Assumptions

1. **Resume is image/scanned**: The OCR pipeline is the primary path. pdfplumber is a performance optimization for text-based PDFs only.
2. **ATS field names vary**: The alias map covers the most common conventions but may need extension for uncommon vendors.
3. **GitHub public profile**: Private profiles with hidden emails are handled gracefully (email field is optional).
4. **Country detection from location**: The system tries to infer the country from the location string. If it fails, the country field is left null (not guessed).
5. **Phone country hint from location**: If a phone number is ambiguous (no country code), the candidate's detected country is used as a hint.

---

## Future Improvements

1. **LinkedIn parser**: Add LinkedIn profile scraping (currently only URL is extracted).
2. **NLP-based section detection**: Replace regex heuristics with a trained NER model for more robust resume parsing.
3. **Weighted confidence**: Apply field-importance weights to the overall confidence (e.g., name matters more than portfolio URL).
4. **Caching**: Cache GitHub API responses by username to avoid repeated calls.
5. **Batch processing**: Extend the pipeline to process multiple candidates in parallel.
6. **Feedback loop**: Allow recruiters to correct merge decisions, feeding back into confidence tuning.
7. **More skill aliases**: Continuously expand `skill_aliases.json` based on recruiter feedback.
8. **LLM-assisted parsing**: Use an LLM as a fallback for very poorly structured resumes.
9. **Database persistence**: Store canonical profiles in a database instead of JSON files.
10. **REST API wrapper**: Wrap the TransformerService as a FastAPI endpoint for production deployment.
