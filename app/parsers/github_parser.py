"""
github_parser.py — GitHub Profile URL → ParsedSource

Pipeline:
  1. Extract username from URL.
  2. Call GET /users/{username} → name, bio, email, location, website.
  3. Call GET /users/{username}/repos → aggregate programming languages.
  4. Infer skills from language frequencies.
  5. Return ParsedSource.  Never raise — all errors are logged.

Rate-limit handling:
  - Reads GITHUB_TOKEN from environment (via python-dotenv) for 5000 req/hr.
  - On 429 / rate-limit header, logs warning and returns partial data.
  - On 404, marks source as unavailable.

Private email handling:
  - GitHub users may hide their email.  If the /users endpoint returns
    null for email, we skip it gracefully.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from app.models.candidate import ParsedSource, RawField
from app.models.confidence import SourceType, get_base_confidence
from app.utils.helpers import clean_url, is_empty
from app.validators.validators import validate_github_url
from app.utils.logger import get_logger
from config.settings import (
    GITHUB_API_BASE,
    GITHUB_MAX_REPOS,
    GITHUB_REQUEST_TIMEOUT,
    METHOD_GITHUB_API,
)

load_dotenv()

logger = get_logger(__name__)
_GITHUB_CONFIDENCE: float = get_base_confidence(SourceType.GITHUB)

# Minimum number of bytes in a language to count it as a skill
_LANGUAGE_MIN_BYTES: int = 500


class GitHubParser:
    """Parses a GitHub profile URL into a ParsedSource.

    Uses the GitHub REST API v3.  Optionally authenticates via a
    personal access token stored in the ``GITHUB_TOKEN`` environment
    variable, which raises the rate limit from 60 to 5000 req/hr.

    Args:
        token: Optional GitHub personal access token.  If None, reads
               from the ``GITHUB_TOKEN`` environment variable.
    """

    def __init__(self, token: Optional[str] = None) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._session = requests.Session()
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"
        self._session.headers["Accept"] = "application/vnd.github+json"
        self._session.headers["X-GitHub-Api-Version"] = "2022-11-28"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, github_url: str) -> ParsedSource:
        """Parse a GitHub profile URL and return a ParsedSource.

        Args:
            github_url: A GitHub profile URL, e.g. 'https://github.com/torvalds'.

        Returns:
            ParsedSource with extracted fields.  If the URL is invalid
            or the API call fails, ``available`` is set to False.
        """
        errors: list[str] = []
        fields: dict[str, Any] = {}
        list_fields: dict[str, list[Any]] = {}

        username = self._extract_username(github_url)
        if not username:
            msg = f"Could not extract GitHub username from URL: '{github_url}'"
            logger.error(msg)
            return ParsedSource(
                source_type=SourceType.GITHUB,
                fields={},
                list_fields={},
                parse_errors=[msg],
                available=False,
            )

        # --- Fetch user profile ---
        user_data = self._get_user(username, errors)
        if user_data is None:
            return ParsedSource(
                source_type=SourceType.GITHUB,
                fields={},
                list_fields={},
                parse_errors=errors,
                available=False,
            )

        self._extract_user_fields(user_data, fields, errors)

        # --- Fetch repos for language inference ---
        repos = self._get_repos(username, errors)
        skills = self._infer_skills_from_repos(repos, errors)
        if skills:
            list_fields["skills"] = skills

        logger.info(
            "GitHubParser complete — user='%s', %d scalar fields, %d skills, %d errors",
            username,
            len(fields),
            len(skills),
            len(errors),
        )

        return ParsedSource(
            source_type=SourceType.GITHUB,
            fields=fields,
            list_fields=list_fields,
            parse_errors=errors,
            available=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_username(url: str) -> Optional[str]:
        """Extract the username from a GitHub profile URL.

        Supports:
          - https://github.com/username
          - http://github.com/username
          - github.com/username

        Args:
            url: Input URL string.

        Returns:
            Username string, or None if extraction fails or username is invalid.
        """
        url = clean_url(url)
        pattern = r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_-]+)"
        match = re.match(pattern, url, re.IGNORECASE)
        if not match:
            return None
        username = match.group(1)
        # Sanity-check: GitHub usernames are 1-39 chars and must not contain
        # protocol fragments (which would indicate a malformed/concatenated URL).
        if not username or len(username) > 39:
            logger.warning("Extracted GitHub username too long or empty: '%s'", username)
            return None
        if re.search(r"https?", username, re.IGNORECASE):
            logger.warning(
                "Extracted GitHub username looks like a concatenated URL fragment: '%s'. "
                "Discarding.", username
            )
            return None
        return username

    def _get(self, url: str, errors: list[str]) -> Optional[dict[str, Any]]:
        """Make an authenticated GET request to the GitHub API.

        Args:
            url:    Full API URL.
            errors: Error list to append to on failure.

        Returns:
            Parsed JSON dict, or None on error.
        """
        try:
            resp = self._session.get(url, timeout=GITHUB_REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                msg = f"GitHub API 404 for URL: {url}"
                logger.warning(msg)
                errors.append(msg)
                return None
            elif resp.status_code == 403:
                # Rate limit
                remaining = resp.headers.get("X-RateLimit-Remaining", "?")
                msg = (
                    f"GitHub API rate-limited (403). "
                    f"Remaining calls: {remaining}. "
                    "Set GITHUB_TOKEN env var for 5000 req/hr."
                )
                logger.warning(msg)
                errors.append(msg)
                return None
            elif resp.status_code == 429:
                msg = f"GitHub API rate-limited (429) for URL: {url}"
                logger.warning(msg)
                errors.append(msg)
                return None
            else:
                msg = f"GitHub API returned {resp.status_code} for URL: {url}"
                logger.warning(msg)
                errors.append(msg)
                return None
        except requests.Timeout:
            msg = f"GitHub API timed out after {GITHUB_REQUEST_TIMEOUT}s for: {url}"
            logger.error(msg)
            errors.append(msg)
            return None
        except requests.RequestException as exc:
            msg = f"GitHub API request error for {url}: {exc}"
            logger.error(msg)
            errors.append(msg)
            return None

    def _get_user(
        self, username: str, errors: list[str]
    ) -> Optional[dict[str, Any]]:
        """Fetch the /users/{username} endpoint."""
        url = f"{GITHUB_API_BASE}/users/{username}"
        return self._get(url, errors)

    def _get_repos(
        self, username: str, errors: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch up to GITHUB_MAX_REPOS public repos."""
        url = (
            f"{GITHUB_API_BASE}/users/{username}/repos"
            f"?per_page={min(GITHUB_MAX_REPOS, 100)}&sort=pushed"
        )
        result = self._get(url, errors)
        if isinstance(result, list):
            return result
        # Sometimes the API returns a dict with error info
        return []

    def _extract_user_fields(
        self,
        user_data: dict[str, Any],
        fields: dict[str, Any],
        errors: list[str],
    ) -> None:
        """Extract scalar fields from /users/{username} response."""
        def _wrap(value: Any, raw: Any = None) -> RawField:
            return RawField(
                value=value,
                source=SourceType.GITHUB,
                confidence=_GITHUB_CONFIDENCE,
                method=METHOD_GITHUB_API,
                raw=raw if raw is not None else value,
            )

        try:
            # Name
            name = user_data.get("name") or ""
            if not is_empty(name):
                fields["full_name"] = _wrap(name.strip())

            # Email (may be null if user hides it)
            email = user_data.get("email") or ""
            if not is_empty(email):
                fields["_github_email"] = _wrap(email.strip())
                # Also push into emails list_field caller
                # The merge engine reads 'emails' from list_fields
                # We inject it into list_fields via the caller; stored here for now.

            # Bio → headline
            bio = user_data.get("bio") or ""
            if not is_empty(bio):
                fields["headline"] = _wrap(bio.strip())

            # Location
            location = user_data.get("location") or ""
            if not is_empty(location):
                fields["location"] = _wrap(location.strip())

            # Website / blog → portfolio
            blog = user_data.get("blog") or ""
            if not is_empty(blog):
                blog = clean_url(str(blog))
                fields["_github_blog"] = _wrap(blog)

            # Links sub-dict
            links: dict[str, str] = {
                "github": clean_url(user_data.get("html_url", "")),
            }
            if not is_empty(blog):
                links["portfolio"] = blog
            fields["links"] = _wrap(links)

        except Exception as exc:
            msg = f"Error extracting GitHub user fields: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

    def _infer_skills_from_repos(
        self,
        repos: list[dict[str, Any]],
        errors: list[str],
    ) -> list[RawField]:
        """Aggregate programming languages from repos as skills.

        Counts by number of repos using each language (not bytes, since
        we only have top-language-per-repo at this endpoint level).

        Args:
            repos:  List of repo dicts from the GitHub API.
            errors: Error list to append to on failure.

        Returns:
            List of RawField[str] — one per unique language detected.
        """
        lang_counts: dict[str, int] = {}
        for repo in repos:
            lang = repo.get("language")
            if lang and isinstance(lang, str):
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

        if not lang_counts:
            logger.debug("No languages found in GitHub repos.")
            return []

        # Sort by frequency (most common first) for determinism
        sorted_langs = sorted(lang_counts.items(), key=lambda x: (-x[1], x[0]))
        skills: list[RawField] = []
        for lang, count in sorted_langs:
            try:
                skills.append(
                    RawField(
                        value=lang,
                        source=SourceType.GITHUB,
                        confidence=_GITHUB_CONFIDENCE,
                        method=METHOD_GITHUB_API,
                        raw=f"{lang} ({count} repos)",
                    )
                )
            except Exception as exc:
                errors.append(f"Error wrapping language '{lang}': {exc}")

        logger.debug("Inferred %d skills from GitHub repos", len(skills))
        return skills


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def parse_github(github_url: str, token: Optional[str] = None) -> ParsedSource:
    """Convenience function: parse a GitHub URL without instantiating the class.

    Args:
        github_url: GitHub profile URL.
        token:      Optional personal access token.

    Returns:
        ParsedSource.
    """
    return GitHubParser(token=token).parse(github_url)
