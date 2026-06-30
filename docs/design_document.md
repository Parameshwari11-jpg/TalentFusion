# Design Document — Multi-Source Candidate Data Transformer

**Author:** EightFold AI Internship Assignment  
**Version:** 1.0  
**Date:** 2026-06-30

---

## 1. System Overview

The Multi-Source Candidate Data Transformer ingests raw candidate data from three heterogeneous sources — a structured ATS JSON export, a scanned resume PDF, and a GitHub profile — and produces a single trusted canonical candidate profile with full confidence scoring, conflict resolution logging, and provenance tracking.

---

## 2. Architecture

```
┌──────────────────── INPUT LAYER ────────────────────┐
│  ATS JSON    │  Scanned PDF    │  GitHub URL         │
└──────┬────────────────┬────────────────┬─────────────┘
       ▼                ▼                ▼
  ATSParser       ResumeParser      GitHubParser
  (alias map)     (OCR pipeline)    (REST API)
       │                │                │
       └────────────────┴────────────────┘
                        │
                 ParsedSource ×3
              (RawField[T] per value)
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
       Normalization         MergeEngine
       ├─ Phone → E.164      ├─ FieldMerger
       ├─ Date → YYYY-MM     ├─ ListMerger
       ├─ Skill → canonical  ├─ ConfidenceEngine
       ├─ Location → ISO-α2  └─ ProvenanceTracker
       ├─ Email validate
       └─ Name title-case
                        │
               CanonicalCandidate
               (Pydantic, validated)
                        │
              ProjectionEngine
              (config-driven)
                        │
                 Output JSON
```

---

## 3. Data Flow

### 3.1 Parsing Phase
Each parser runs independently and returns a `ParsedSource` object containing `RawField[T]` instances — typed value containers that carry the source label, confidence, extraction method, and raw value for provenance.

If a parser fails, it returns `ParsedSource(available=False)`, which is silently skipped by the merge engine.

### 3.2 Normalization Phase
Applied before merging:

| Field | Library | Output |
|-------|---------|--------|
| Phone | `phonenumbers` | E.164 (`+16505550192`) |
| Date | `dateparser` + regex | `YYYY-MM` (`2024-01`) |
| Skill | alias map + `rapidfuzz` | Canonical name (`JavaScript`) |
| Location | `pycountry` + override table | ISO-3166 α-2 (`US`) |
| Email | `email-validator` | Lowercased, validated |
| Name | stdlib | Title Case, trimmed |

### 3.3 Merge Phase
For each canonical field, the merge engine:
1. Collects all `RawField` values from all sources.
2. Groups values by normalised content.
3. Computes agreement-bonus confidence.
4. Selects the winning value (highest confidence; ATS > Resume > GitHub for ties).
5. Records full provenance for every candidate.

For list fields (skills, emails, phones, experience, education), deduplication is performed before merging.

### 3.4 Projection Phase
The `ProjectionEngine` reads a runtime JSON config and shapes the output without modifying the canonical model. This enables multiple downstream consumers with different field requirements.

---

## 4. Confidence Model

### Base Scores
| Source | Base Confidence |
|--------|----------------|
| ATS | 0.95 |
| Resume | 0.85 |
| GitHub | 0.80 |
| Invalid data | 0.20 |

### Agreement Bonus
When multiple sources agree on the same normalised value, a higher confidence is applied:

| Agreement | Final Confidence |
|-----------|----------------|
| ATS only | 0.95 |
| Resume only | 0.85 |
| GitHub only | 0.80 |
| ATS + Resume | 0.98 |
| ATS + GitHub | 0.97 |
| Resume + GitHub | 0.93 |
| All three | 1.00 |

---

## 5. Conflict Resolution

**Rule**: Highest confidence wins.

**Tie-breaking**: Source priority order: ATS > Resume > GitHub.

**Example**:
```
ATS:    "Google"   → confidence 0.95
Resume: "Amazon"   → confidence 0.85
GitHub: (empty)

→ Selected: "Google" (ATS, higher confidence)
→ Rejected: "Amazon" (logged with reason)
```

**Skill merging** (union with deduplication):
```
ATS:    ["Python", "JS"]      → ["Python", "JavaScript"]
Resume: ["Python", "Docker"]  → ["Python", "Docker"]
GitHub: ["Python"]            → ["Python"]

→ Merged: ["Python", "JavaScript", "Docker"]
          Python confidence: 1.00 (all 3 agree)
          JavaScript confidence: 0.95 (ATS only)
          Docker confidence: 0.85 (Resume only)
```

---

## 6. Normalization Examples

### Phone
```
Input:  "+1-650-555-0192"          → "+16505550192"
Input:  "9876543210" + country=IN  → "+919876543210"
Input:  "not-a-phone"              → "not-a-phone" (confidence: 0.20)
```

### Date
```
"January 2024"  → "2024-01"
"Jan 2024"      → "2024-01"
"01/2024"       → "2024-01"
"Present"       → "Present"
"2019"          → "2019-01"
```

### Skill
```
"JS"          → "JavaScript" (exact alias)
"java script" → "JavaScript" (exact alias)
"pythn"       → "Python" (fuzzy match, score ≥ 82)
"QuantumML"   → "QuantumML" (passthrough, no match)
```

### Location
```
"San Francisco, CA, United States" → city: "San Francisco", state: "CA", country: "US"
"Bangalore, India"                 → city: "Bangalore", country: "IN"
"London, UK"                       → city: "London", country: "GB"
```

---

## 7. Projection Engine

The `ProjectionConfig` schema:

```json
{
  "fields": ["full_name", "emails", "skills"],
  "rename": {"full_name": "name"},
  "include_confidence": true,
  "include_provenance": false,
  "missing_field_policy": "omit"
}
```

| `missing_field_policy` | Behavior |
|------------------------|----------|
| `"null"` | Field included with `null` value |
| `"omit"` | Field excluded from output |
| `"error"` | `ValueError` raised |

---

## 8. OCR Pipeline

```
PDF input
  └─> pdfplumber (fast path: text PDFs)
        └─ if text < 100 chars:
             pdf2image (DPI=300) → PIL Images
               └─> OpenCV preprocessing:
                     grayscale → Otsu binarize → deskew → denoise
                       └─> pytesseract (--psm 6, lang=eng)
                             └─> raw text
                                   └─> section splitter (regex headings)
                                         └─> contact / skills / experience / education parsers
```

---

## 9. Edge Cases Handled

| Edge Case | Handling |
|-----------|----------|
| Broken PDF (corrupted) | `available=False`, logged |
| GitHub 404 | `available=False`, logged |
| GitHub rate-limit (403/429) | `available=False`, warning logged |
| Private GitHub email | Gracefully skipped |
| Invalid email | Kept with confidence 0.20 |
| Invalid phone | Kept as-is with confidence 0.20 |
| Unknown country | `country=null`, location still usable |
| ATS with no skills field | Empty list, no crash |
| All-uppercase name ("JOHN DOE") | Title-cased to "John Doe" |
| Missing start/end dates | `null`, no crash |
| Experience with no company | Skipped in deduplication |
| Tesseract not installed | Clear error message in UI |

---

## 10. Trade-offs

| Decision | Trade-off |
|----------|-----------|
| Regex-based section splitting | Fast and deterministic, but may fail on unusual resume layouts |
| RapidFuzz for skills | ~82% threshold catches common typos but may misclassify edge cases |
| pdfplumber fast-path | Skips OCR for text PDFs (faster), but assumes pdfplumber text is clean |
| UUID candidate_id per run | Not stable across runs (by design — each call is independent) |
| In-memory merge log | Sufficient for single-candidate use; a DB would be needed for scale |
| Source priority tie-breaking | ATS-biased, which is appropriate for recruiter-verified data |

---

## 11. Key Design Principles

- **SOLID**: Each class has one responsibility. FieldMerger only merges scalars; ListMerger only merges lists.
- **DRY**: Confidence constants defined once in `config/settings.py`.
- **Composition over inheritance**: No deep class hierarchies; modules are composed in `transformer_service.py`.
- **Never crash**: Every parser, normalizer, and merger has `try/except` at all boundaries.
- **Deterministic**: No randomness; sorted comparisons ensure stable ordering.
- **Explainable**: `merge_log.json` + provenance records provide full auditability.
