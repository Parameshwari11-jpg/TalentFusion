"""
resume_parser.py — Scanned Resume PDF → ParsedSource

OCR Pipeline:
  PDF file
    → pdf2image (convert pages to PIL Images at OCR_DPI)
      → OpenCV pre-processing (deskew, denoise, threshold)
        → pytesseract OCR (extract raw text)
          → Section splitter (heuristic heading detection)
            → Per-section parsers (contact, skills, experience, education)
              → ParsedSource

Design decisions:
  - We NEVER assume the PDF is text-based.  All text is extracted via OCR.
  - pdfplumber is used as a fast-path fallback for text-based PDFs to
    improve accuracy when OCR is unnecessary.
  - OpenCV pre-processing significantly improves OCR accuracy on scanned docs.
  - Section detection uses regex heading patterns (robust across formats).
  - All failures degrade gracefully — partial data is always better than none.

Prerequisites:
  - Tesseract OCR must be installed on the system.
    Windows: https://github.com/UB-Mannheim/tesseract/wiki
    Linux:   sudo apt-get install tesseract-ocr
  - poppler must be installed for pdf2image.
    Windows: https://github.com/oschwartz10612/poppler-windows/releases
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Optional, Union

import cv2
import numpy as np
import pdfplumber
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes, convert_from_path

from app.models.candidate import ParsedSource, RawField
from app.models.confidence import SourceType, get_base_confidence
from app.utils.helpers import (
    extract_years_from_text,
    is_empty,
    normalize_whitespace,
)
from app.utils.logger import get_logger
from config.settings import METHOD_RESUME_OCR, OCR_DPI, OCR_LANG

logger = get_logger(__name__)
_RESUME_CONFIDENCE: float = get_base_confidence(SourceType.RESUME)

# ---------------------------------------------------------------------------
# Section heading patterns (case-insensitive)
# ---------------------------------------------------------------------------
_SECTION_PATTERNS: dict[str, list[str]] = {
    "contact": [
        r"contact(\s+information)?",
        r"personal(\s+details)?",
        r"profile",
    ],
    "summary": [
        r"summary",
        r"objective",
        r"professional\s+summary",
        r"about(\s+me)?",
        r"career\s+objective",
    ],
    "skills": [
        r"(technical\s+)?skills",
        r"competencies",
        r"technologies",
        r"tech(nical)?\s+stack",
        r"expertise",
        r"key\s+skills",
    ],
    "experience": [
        r"(work\s+|professional\s+)?experience",
        r"employment(\s+history)?",
        r"work\s+history",
        r"career\s+history",
    ],
    "education": [
        r"education(\s+history)?",
        r"academic(\s+(background|history))?",
        r"qualifications?",
    ],
    "projects": [
        r"projects?",
        r"personal\s+projects?",
        r"side\s+projects?",
    ],
    "certifications": [
        r"certifications?",
        r"certificates?",
        r"courses?",
        r"achievements?",
    ],
}

# Pre-compile heading pattern for section detection
_HEADING_RE = re.compile(
    r"^(" + "|".join(
        f"(?:{p})"
        for patterns in _SECTION_PATTERNS.values()
        for p in patterns
    ) + r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class ResumeParser:
    """Parses a scanned resume PDF into a ParsedSource via OCR.

    Args:
        poppler_path: Optional path to the poppler bin directory
                      (required on Windows if poppler is not in PATH).
        tesseract_cmd: Optional path to the tesseract executable.
    """

    def __init__(
        self,
        poppler_path: Optional[str] = None,
        tesseract_cmd: Optional[str] = None,
    ) -> None:
        self._poppler_path = poppler_path
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(
        self,
        source: Union[Path, bytes, io.BytesIO],
    ) -> ParsedSource:
        """Parse a resume PDF and return a ParsedSource.

        Args:
            source: Path to a PDF file, raw bytes, or a BytesIO object.

        Returns:
            ParsedSource with extracted fields.
        """
        errors: list[str] = []
        fields: dict[str, Any] = {}
        list_fields: dict[str, list[Any]] = {}

        # --- Step 1: Extract text ---
        full_text, contact_text = self._extract_text(source, errors)
        if not full_text.strip():
            msg = "No text could be extracted from the resume PDF."
            logger.warning(msg)
            errors.append(msg)
            return ParsedSource(
                source_type=SourceType.RESUME,
                fields={},
                list_fields={},
                parse_errors=errors,
                available=False,
            )

        # --- Step 2: Split into sections ---
        sections = self._split_into_sections(full_text)
        logger.debug("Detected sections: %s", list(sections.keys()))

        # --- Step 3: Parse each section ---
        self._parse_contact(contact_text, sections, fields, list_fields, errors)
        self._parse_summary(sections, fields, errors)
        self._parse_skills(sections, list_fields, errors)
        self._parse_experience(sections, list_fields, errors)
        self._parse_education(sections, list_fields, errors)
        self._parse_years_experience(full_text, sections, fields, errors)

        logger.info(
            "ResumeParser complete — %d scalar fields, %d list fields, %d errors",
            len(fields),
            len(list_fields),
            len(errors),
        )
        return ParsedSource(
            source_type=SourceType.RESUME,
            fields=fields,
            list_fields=list_fields,
            parse_errors=errors,
            available=True,
        )

    # ------------------------------------------------------------------
    # Text extraction helpers
    # ------------------------------------------------------------------

    def _extract_text(
        self,
        source: Union[Path, bytes, io.BytesIO],
        errors: list[str],
    ) -> tuple[str, str]:
        """Extract full text and contact-specific text from a PDF.

        Fast path: pdfplumber for any PDF that yields readable text (>100 chars).
        Only falls back to the heavy OCR pipeline when pdfplumber returns nothing
        (i.e. a purely image-based / scanned PDF).

        Returns:
            Tuple of (full_text, contact_text).
        """
        pdf_bytes: bytes = self._to_bytes(source, errors)
        if not pdf_bytes:
            return "", ""

        # Fast path: pdfplumber — works for digital (selectable-text) PDFs.
        digital_text = self._extract_with_pdfplumber(pdf_bytes, errors)
        if digital_text and len(digital_text.strip()) > 100:
            logger.debug("Text extracted via pdfplumber (text-based PDF) — skipping OCR.")
            return digital_text, digital_text

        # Fallback: full OCR pipeline for image-only scanned PDFs.
        logger.debug("pdfplumber returned no usable text — falling back to OCR pipeline.")
        ocr_text = self._extract_with_ocr(pdf_bytes, errors)
        return ocr_text, ocr_text

    @staticmethod
    def _is_glued_text(text: str) -> bool:
        """Heuristically check if the text has words glued together (missing spaces)."""
        words = text.split()
        if not words:
            return True
        # Check if any word has a very long run of purely alphabetic characters
        for w in words:
            alpha_only = re.sub(r"[^A-Za-z]", "", w)
            if len(alpha_only) > 25:
                return True
        # Check overall space density
        spaces = text.count(" ")
        total_len = len(text)
        if total_len > 0 and (spaces / total_len) < 0.04:
            return True
        return False

    @staticmethod
    def _to_bytes(
        source: Union[Path, bytes, io.BytesIO],
        errors: list[str],
    ) -> bytes:
        """Convert various input types to raw bytes."""
        try:
            if isinstance(source, bytes):
                return source
            if isinstance(source, io.BytesIO):
                source.seek(0)
                return source.read()
            if isinstance(source, Path):
                return source.read_bytes()
            # Streamlit UploadedFile
            if hasattr(source, "read"):
                return source.read()
        except Exception as exc:
            msg = f"Failed to read PDF source: {exc}"
            logger.error(msg)
            errors.append(msg)
        return b""

    @staticmethod
    def _extract_with_pdfplumber(
        pdf_bytes: bytes,
        errors: list[str],
    ) -> str:
        """Extract text using pdfplumber (text-based PDFs only)."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages: list[str] = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    pages.append(page_text)
                return "\n".join(pages)
        except Exception as exc:
            msg = f"pdfplumber extraction failed: {exc}"
            logger.warning(msg)
            errors.append(msg)
            return ""

    def _extract_with_ocr(
        self,
        pdf_bytes: bytes,
        errors: list[str],
    ) -> str:
        """Full OCR pipeline: PDF → Images → pre-process → pytesseract → text."""
        try:
            images = self._pdf_to_images(pdf_bytes, errors)
            if not images:
                return ""
            texts: list[str] = []
            for i, img in enumerate(images):
                try:
                    processed = self._preprocess_image(img)
                    text = pytesseract.image_to_string(
                        processed,
                        lang=OCR_LANG,
                        config="--psm 6",  # Assume uniform block of text
                    )
                    texts.append(text)
                except Exception as exc:
                    msg = f"OCR failed on page {i + 1}: {exc}"
                    logger.warning(msg)
                    errors.append(msg)
            return "\n".join(texts)
        except Exception as exc:
            msg = f"OCR pipeline failed: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)
            return ""

    def _pdf_to_images(
        self,
        pdf_bytes: bytes,
        errors: list[str],
    ) -> list[Image.Image]:
        """Convert PDF pages to PIL Images using pdf2image."""
        try:
            kwargs: dict[str, Any] = {"dpi": OCR_DPI, "fmt": "PNG"}
            if self._poppler_path:
                kwargs["poppler_path"] = self._poppler_path
            return convert_from_bytes(pdf_bytes, **kwargs)
        except Exception as exc:
            msg = f"pdf2image conversion failed: {exc}"
            logger.error(msg)
            errors.append(msg)
            return []

    @staticmethod
    def _preprocess_image(image: Image.Image) -> Image.Image:
        """Apply OpenCV pre-processing to improve OCR accuracy.

        Steps:
          1. Convert to grayscale.
          2. Apply Otsu's binarisation.
          3. Deskew (detect skew angle, rotate to correct).
          4. Remove small noise blobs.

        Args:
            image: PIL Image (RGB or RGBA).

        Returns:
            Processed PIL Image.
        """
        try:
            # PIL → OpenCV (BGR)
            img_np = np.array(image.convert("RGB"))
            gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)

            # Otsu binarisation
            _, binary = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            # Deskew
            binary = ResumeParser._deskew(binary)

            # Morphological denoising
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
            denoised = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            # OpenCV → PIL
            return Image.fromarray(denoised)

        except Exception as exc:
            logger.warning("Image pre-processing failed, using original: %s", exc)
            return image

    @staticmethod
    def _deskew(image: np.ndarray) -> np.ndarray:
        """Detect and correct skew in a binary image."""
        try:
            coords = np.column_stack(np.where(image < 128))
            if len(coords) < 10:
                return image
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) < 0.5:
                return image  # No meaningful skew
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                image, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated
        except Exception:
            return image

    # ------------------------------------------------------------------
    # Section splitting
    # ------------------------------------------------------------------

    @staticmethod
    def _split_into_sections(text: str) -> dict[str, str]:
        """Split resume text into named sections using heading detection.

        Args:
            text: Full resume text.

        Returns:
            Dict mapping section name → section content.
        """
        lines = text.split("\n")
        sections: dict[str, str] = {"_preamble": ""}
        current_section = "_preamble"
        buffer: list[str] = []

        for line in lines:
            stripped = line.strip()
            matched_section = ResumeParser._match_section_heading(stripped)
            if matched_section:
                sections[current_section] = "\n".join(buffer).strip()
                current_section = matched_section
                buffer = []
            else:
                buffer.append(line)

        sections[current_section] = "\n".join(buffer).strip()
        return sections

    @staticmethod
    def _match_section_heading(line: str) -> Optional[str]:
        """Return the canonical section name if the line is a heading."""
        for section, patterns in _SECTION_PATTERNS.items():
            for pattern in patterns:
                if re.fullmatch(pattern + r"\s*:?", line, re.IGNORECASE):
                    return section
        return None

    # ------------------------------------------------------------------
    # Section parsers
    # ------------------------------------------------------------------

    def _wrap(self, value: Any, raw: Any = None) -> RawField:
        """Create a RawField tagged for Resume source."""
        return RawField(
            value=value,
            source=SourceType.RESUME,
            confidence=_RESUME_CONFIDENCE,
            method=METHOD_RESUME_OCR,
            raw=raw if raw is not None else value,
        )

    def _parse_contact(
        self,
        contact_text: str,
        sections: dict[str, str],
        fields: dict[str, Any],
        list_fields: dict[str, list[Any]],
        errors: list[str],
    ) -> None:
        """Extract contact info: name, emails, phones, links, location from preamble/header."""
        # Use first ~20 lines as contact region
        header_text = "\n".join(contact_text.split("\n")[:20])
        contact_section = sections.get("contact", "") + "\n" + header_text

        # --- Emails ---
        emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", contact_section)
        if emails:
            list_fields["emails"] = [
                self._wrap(e.lower(), raw=e) for e in dict.fromkeys(emails)
            ]

        # --- Phones ---
        # Match common phone formats, requiring at least 7 digits, avoiding simple decimals/years
        # We match spaces, tabs, dots, hyphens, but NOT newlines (\s matches newlines)
        phones = re.findall(
            r"(?:\+?\d{1,4}[-. \t]?)?\(?\d{2,4}\)?[-. \t]?\d{3,4}[-. \t]?\d{3,4}", contact_section
        )
        if phones:
            valid_extracted_phones = []
            for p in phones:
                digits_only = re.sub(r"\D", "", p)
                if 7 <= len(digits_only) <= 15:
                    valid_extracted_phones.append(p.strip())
            if valid_extracted_phones:
                list_fields["phones"] = [
                    self._wrap(p, raw=p) for p in dict.fromkeys(valid_extracted_phones)
                ]

        # --- Name: first non-empty line of the document ---
        first_lines = [l.strip() for l in contact_text.split("\n") if l.strip()]
        if first_lines:
            # Heuristic: name is the first 1-4 word line that contains only letters/spaces
            for line in first_lines[:5]:
                if re.fullmatch(r"[A-Za-z][\w\s'\-\.]{1,50}", line) and len(line.split()) <= 5:
                    if not re.search(r"@|http|www|\d{5}", line):
                        fields["full_name"] = self._wrap(line, raw=line)
                        break

        # --- LinkedIn ---
        linkedin_pattern = r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-\./]+"
        linkedin_matches = []
        for match in re.finditer(linkedin_pattern, contact_section, re.IGNORECASE):
            url = match.group(0)
            end = match.end()
            if url.lower().endswith("https") and contact_section[end:end+3] == "://":
                url = url[:-5]
            elif url.lower().endswith("http") and contact_section[end:end+3] == "://":
                url = url[:-4]
            linkedin_matches.append(url)

        if linkedin_matches:
            links_value = fields.get("links", {})
            if isinstance(links_value, RawField):
                links_value = links_value.value
            # Ensure it has a scheme
            url = linkedin_matches[0]
            if not url.lower().startswith("http"):
                url = "https://" + url
            links_value["linkedin"] = url
            fields["links"] = self._wrap(links_value)

        # --- GitHub ---
        github_pattern = r"(?:https?://)?(?:www\.)?github\.com/[\w\-\./]+"
        github_matches = []
        for match in re.finditer(github_pattern, contact_section, re.IGNORECASE):
            url = match.group(0)
            end = match.end()
            if url.lower().endswith("https") and contact_section[end:end+3] == "://":
                url = url[:-5]
            elif url.lower().endswith("http") and contact_section[end:end+3] == "://":
                url = url[:-4]
            github_matches.append(url)

        if github_matches:
            links_value = fields.get("links", {})
            if isinstance(links_value, RawField):
                links_value = links_value.value
            # Ensure it has a scheme
            url = github_matches[0]
            if not url.lower().startswith("http"):
                url = "https://" + url
            links_value["github"] = url
            fields["links"] = self._wrap(links_value)

        # --- Location ---
        location_match = re.search(
            r"(?:location|address|residing\s+in|based\s+in)[:\-\u2013\u2014\=]?\s*([A-Za-z0-9\s,]+)",
            contact_section,
            re.IGNORECASE
        )
        if location_match:
            fields["location"] = self._wrap(location_match.group(1).strip(), raw=location_match.group(0))
        else:
            # Fallback: scan lines for known cities or "City, State" patterns
            common_cities = r"\b(coimbatore|chennai|bangalore|bengaluru|mumbai|delhi|hyderabad|pune|kolkata|san francisco|california|tamil nadu|india)\b"
            for line in contact_section.split("\n"):
                if re.search(common_cities, line, re.IGNORECASE):
                    # Exclude lines that look like emails, titles, or schools
                    if not re.search(r"@|http|school|college|university|student|motivated", line, re.IGNORECASE):
                        if len(line.strip()) < 50:
                            fields["location"] = self._wrap(line.strip(), raw=line)
                            break

    def _parse_summary(
        self,
        sections: dict[str, str],
        fields: dict[str, Any],
        errors: list[str],
    ) -> None:
        """Extract professional summary → headline."""
        summary_text = sections.get("summary", "").strip()
        if summary_text:
            # Take first sentence or first 200 chars as headline
            first_sentence = re.split(r"[.\n]", summary_text)[0].strip()
            if first_sentence:
                fields["headline"] = self._wrap(first_sentence[:300])

    def _parse_skills(
        self,
        sections: dict[str, str],
        list_fields: dict[str, list[Any]],
        errors: list[str],
    ) -> None:
        """Extract skills from the skills section."""
        skills_text = sections.get("skills", "").strip()
        if not skills_text:
            return

        # Split on common delimiters: comma, bullet, pipe, newline
        raw_skills = re.split(r"[,•|·\n\t]+", skills_text)
        cleaned: list[str] = []
        for s in raw_skills:
            s = normalize_whitespace(s.strip(" -–—•"))
            if s and 2 <= len(s) <= 60:
                cleaned.append(s)

        if cleaned:
            list_fields["skills"] = [
                self._wrap(s, raw=s) for s in dict.fromkeys(cleaned)
            ]

    def _parse_experience(
        self,
        sections: dict[str, str],
        list_fields: dict[str, list[Any]],
        errors: list[str],
    ) -> None:
        """Extract work experience entries from the experience section."""
        exp_text = sections.get("experience", "").strip()
        if not exp_text:
            return

        entries = self._split_experience_entries(exp_text)
        raw_fields: list[RawField] = []
        for entry_text in entries:
            try:
                entry = self._parse_single_experience(entry_text)
                if entry:
                    raw_fields.append(self._wrap(entry, raw=entry_text))
            except Exception as exc:
                msg = f"Error parsing experience entry: {exc}"
                logger.warning(msg)
                errors.append(msg)

        if raw_fields:
            list_fields["experience"] = raw_fields

    @staticmethod
    def _split_experience_entries(text: str) -> list[str]:
        """Heuristically split experience section into individual entries."""
        # Split on lines that look like company/role headers (contain year ranges)
        date_pattern = re.compile(
            r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
            r"January|February|March|April|June|July|August|September|"
            r"October|November|December|\d{4})\b",
            re.IGNORECASE,
        )
        lines = text.split("\n")
        entries: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if date_pattern.search(line) and current and len(line.strip()) < 150:
                # Likely a new entry header
                entries.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            entries.append(current)
        return ["\n".join(e).strip() for e in entries if "\n".join(e).strip()]

    @staticmethod
    def _parse_single_experience(entry_text: str) -> Optional[dict[str, Any]]:
        """Parse a single experience entry block into a dict."""
        lines = [l.strip() for l in entry_text.split("\n") if l.strip()]
        if not lines:
            return None

        # Heuristic: first line = title/company, subsequent lines = description
        result: dict[str, Any] = {
            "title": "",
            "company": "",
            "description": "",
        }

        # Extract dates
        date_pattern = re.compile(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|"
            r"February|March|April|June|July|August|September|October|"
            r"November|December)?\s*\d{4}|Present)",
            re.IGNORECASE,
        )
        dates = date_pattern.findall("\n".join(lines[:3]))
        if len(dates) >= 2:
            result["start_date"] = dates[0]
            result["end_date"] = dates[1]
        elif len(dates) == 1:
            result["start_date"] = dates[0]

        # First line: title @ company (common formats)
        header = lines[0]
        if " at " in header.lower():
            parts = re.split(r"\s+at\s+", header, maxsplit=1, flags=re.IGNORECASE)
            result["title"] = parts[0].strip()
            result["company"] = parts[1].strip()
        elif " - " in header or " – " in header:
            parts = re.split(r"\s+[-–]\s+", header, maxsplit=1)
            result["title"] = parts[0].strip()
            if len(parts) > 1:
                result["company"] = parts[1].strip()
        else:
            result["title"] = header
            if len(lines) > 1:
                result["company"] = lines[1]

        # Remaining lines → description
        result["description"] = normalize_whitespace(" ".join(lines[2:]))

        # Only return if we have at least a title
        return result if result["title"] else None

    def _parse_education(
        self,
        sections: dict[str, str],
        list_fields: dict[str, list[Any]],
        errors: list[str],
    ) -> None:
        """Extract education entries from the education section."""
        edu_text = sections.get("education", "").strip()
        if not edu_text:
            return

        entries = edu_text.strip().split("\n\n") or [edu_text]
        raw_fields: list[RawField] = []
        for entry_text in entries:
            entry_text = entry_text.strip()
            if not entry_text:
                continue
            try:
                entry = self._parse_single_education(entry_text)
                if entry:
                    raw_fields.append(self._wrap(entry, raw=entry_text))
            except Exception as exc:
                msg = f"Error parsing education entry: {exc}"
                logger.warning(msg)
                errors.append(msg)

        if raw_fields:
            list_fields["education"] = raw_fields

    @staticmethod
    def _parse_single_education(entry_text: str) -> Optional[dict[str, Any]]:
        """Parse a single education block."""
        lines = [l.strip() for l in entry_text.split("\n") if l.strip()]
        if not lines:
            return None

        result: dict[str, Any] = {"institution": lines[0]}

        if len(lines) > 1:
            # Second line often has degree and field
            degree_line = lines[1]
            degree_patterns = [
                r"(Bachelor|Master|PhD|Doctor|B\.?Tech|M\.?Tech|B\.?Sc|M\.?Sc|MBA|BCA|MCA)",
            ]
            for p in degree_patterns:
                m = re.search(p, degree_line, re.IGNORECASE)
                if m:
                    result["degree"] = m.group(0)
                    break

            # Extract year
            year_match = re.search(r"\b(\d{4})\b", degree_line)
            if year_match:
                result["end_date"] = year_match.group(1)

        # GPA / CGPA / Percentage
        gpa_val = None
        # Pattern 1: label followed by separator and number (e.g. CGPA: 8.79, Percentage - 92%)
        label_match = re.search(
            r"(?:gpa|cgpa|percentage|percent|marks|grade|score|percentage\s*score)\s*[:\-\u2013\u2014\=]?\s*(\d+(?:\.\d+)?)(?:\s*/\s*\d+)?[%\s]*",
            entry_text,
            re.IGNORECASE
        )
        if label_match:
            gpa_val = label_match.group(1)
        else:
            # Pattern 2: number followed by % or label (e.g. 92%, 8.79 CGPA)
            suffix_match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:%|\s*(?:gpa|cgpa|percentage|percent|marks|grade))",
                entry_text,
                re.IGNORECASE
            )
            if suffix_match:
                gpa_val = suffix_match.group(1)

        if gpa_val:
            try:
                result["gpa"] = float(gpa_val)
            except ValueError:
                pass

        return result if result.get("institution") else None

    def _parse_years_experience(
        self,
        full_text: str,
        sections: dict[str, str],
        fields: dict[str, Any],
        errors: list[str],
    ) -> None:
        """Try to extract total years of experience from summary/objective."""
        search_text = sections.get("summary", "") + "\n" + full_text[:500]
        years = extract_years_from_text(search_text)
        if years is not None:
            fields["years_experience"] = self._wrap(years, raw=f"{years} years")


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def parse_resume(
    source: Union[Path, bytes, io.BytesIO],
    poppler_path: Optional[str] = None,
) -> ParsedSource:
    """Convenience function: parse a resume PDF without instantiating the class.

    Args:
        source:       Path, bytes, or BytesIO of the PDF.
        poppler_path: Optional path to poppler binaries (Windows).

    Returns:
        ParsedSource.
    """
    return ResumeParser(poppler_path=poppler_path).parse(source)
