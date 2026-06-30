"""
transformer_service.py — End-to-end pipeline orchestrator.

The TransformerService is the single entry point that the UI calls.
It:
  1. Invokes each parser (ATS, Resume, GitHub) with graceful failure.
  2. Passes ParsedSource objects to the MergeEngine.
  3. Passes the CanonicalCandidate to the ProjectionEngine.
  4. Returns the projected output dict plus the canonical candidate.

This service layer decouples the UI from the internal pipeline.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Optional, Union

from dotenv import load_dotenv

# Load .env from project root (silently ignored if file doesn't exist)
load_dotenv(override=True)

from app.merger.merge_engine import MergeEngine
from app.models.candidate import CanonicalCandidate, ParsedSource
from app.models.confidence import SourceType
from app.parsers.ats_parser import ATSParser
from app.parsers.github_parser import GitHubParser
from app.parsers.resume_parser import ResumeParser
from app.projection.projection_engine import ProjectionConfig, ProjectionEngine
from app.utils.logger import get_logger
from app.validators.validators import validate_github_url

logger = get_logger(__name__)


class TransformerService:
    """Orchestrates the full candidate data transformation pipeline.

    Args:
        poppler_path:     Optional path to poppler binaries (Windows).
        tesseract_cmd:    Optional path to tesseract executable.
        github_token:     Optional GitHub personal access token.
    """

    def __init__(
        self,
        poppler_path: Optional[str] = None,
        tesseract_cmd: Optional[str] = None,
        github_token: Optional[str] = None,
    ) -> None:
        # Read from .env if not explicitly provided
        resolved_tesseract = tesseract_cmd or os.getenv("TESSERACT_CMD")
        resolved_poppler = poppler_path or os.getenv("POPPLER_PATH") or None

        if resolved_tesseract:
            logger.info("Tesseract path: %s", resolved_tesseract)
        if resolved_poppler:
            logger.info("Poppler path: %s", resolved_poppler)

        self._ats_parser = ATSParser()
        self._resume_parser = ResumeParser(
            poppler_path=resolved_poppler,
            tesseract_cmd=resolved_tesseract,
        )
        self._github_parser = GitHubParser(token=github_token)
        self._merge_engine = MergeEngine()
        self._projection_engine = ProjectionEngine()


    def transform(
        self,
        ats_data: Optional[dict[str, Any]] = None,
        resume_source: Optional[Union[Path, bytes, io.BytesIO]] = None,
        github_url: Optional[str] = None,
        output_config: Optional[dict[str, Any]] = None,
    ) -> tuple[CanonicalCandidate, dict[str, Any], list[dict]]:
        """Run the full pipeline for one candidate.

        At least one source must be provided.  Missing sources are logged
        and skipped gracefully.

        Args:
            ats_data:      ATS JSON payload as a dict.
            resume_source: Resume PDF as Path, bytes, or BytesIO.
            github_url:    GitHub profile URL string.
            output_config: Projection config dict (from uploaded JSON).

        Returns:
            Tuple of:
              - CanonicalCandidate: The fully merged profile.
              - dict: The projected output JSON.
              - list[dict]: Parse errors from all sources (for UI display).
        """
        sources: list[ParsedSource] = []
        all_errors: list[dict] = []

        # --- ATS ---
        if ats_data:
            logger.info("Parsing ATS data...")
            try:
                ats_source = self._ats_parser.parse(ats_data)
                sources.append(ats_source)
                if ats_source.parse_errors:
                    all_errors.append({"source": "ATS", "errors": ats_source.parse_errors})
            except Exception as exc:
                msg = f"ATS parser crashed: {exc}"
                logger.error(msg, exc_info=True)
                all_errors.append({"source": "ATS", "errors": [msg]})
                sources.append(ParsedSource(
                    source_type=SourceType.ATS, available=False,
                    parse_errors=[msg],
                ))
        else:
            logger.info("No ATS data provided — skipping.")

        # --- Resume ---
        if resume_source is not None:
            logger.info("Parsing Resume PDF...")
            try:
                resume_parsed = self._resume_parser.parse(resume_source)
                sources.append(resume_parsed)
                if resume_parsed.parse_errors:
                    all_errors.append({
                        "source": "Resume",
                        "errors": resume_parsed.parse_errors,
                    })
            except Exception as exc:
                msg = f"Resume parser crashed: {exc}"
                logger.error(msg, exc_info=True)
                all_errors.append({"source": "Resume", "errors": [msg]})
                sources.append(ParsedSource(
                    source_type=SourceType.RESUME, available=False,
                    parse_errors=[msg],
                ))
        else:
            logger.info("No resume PDF provided — skipping.")

        # --- GitHub ---
        resolved_github_url = github_url
        if not resolved_github_url or not resolved_github_url.strip():
            # 1. Try to find in ATS links
            if ats_data:
                for k in ["github", "github_url", "githubUrl"]:
                    if ats_data.get(k):
                        resolved_github_url = str(ats_data[k])
                        break
            # 2. Try to find in parsed Resume links
            if not resolved_github_url:
                for s in sources:
                    if s.source_type == SourceType.RESUME and s.available:
                        links_rf = s.fields.get("links")
                        if links_rf and isinstance(links_rf.value, dict):
                            resolved_github_url = links_rf.value.get("github")
                            break

        if resolved_github_url and resolved_github_url.strip():
            # Pre-flight: validate URL format before making API calls
            url_to_check = resolved_github_url.strip()
            if not url_to_check.startswith("http"):
                url_to_check = "https://" + url_to_check
            is_valid_url, url_err = validate_github_url(url_to_check)
            if not is_valid_url:
                msg = (
                    f"Skipping GitHub parsing — invalid URL '{resolved_github_url}': "
                    f"{url_err}"
                )
                logger.warning(msg)
                all_errors.append({"source": "GitHub", "errors": [msg]})
            else:
                logger.info("Parsing GitHub profile: %s", url_to_check)
                try:
                    github_parsed = self._github_parser.parse(url_to_check)
                    sources.append(github_parsed)
                    if github_parsed.parse_errors:
                        all_errors.append({
                            "source": "GitHub",
                            "errors": github_parsed.parse_errors,
                        })
                except Exception as exc:
                    msg = f"GitHub parser crashed: {exc}"
                    logger.error(msg, exc_info=True)
                    all_errors.append({"source": "GitHub", "errors": [msg]})
        else:
            logger.info("No GitHub URL provided or found — skipping.")

        # --- Merge ---
        merge_engine = MergeEngine()
        canonical = merge_engine.merge(sources)

        # --- Project ---
        cfg = (
            ProjectionConfig.from_dict(output_config)
            if output_config
            else ProjectionConfig.default()
        )
        try:
            projected = self._projection_engine.project(canonical, cfg)
        except ValueError as exc:
            # missing_field_policy='error' triggered
            logger.error("Projection failed: %s", exc)
            raise

        logger.info("Pipeline complete — candidate_id=%s", canonical.candidate_id)
        return canonical, projected, all_errors
