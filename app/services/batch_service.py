"""
batch_service.py — Batch orchestration layer for multi-candidate processing.

Calls TransformerService.transform() sequentially for each candidate slot
and returns a structured list of per-candidate results.

Each candidate slot is a dict with optional keys:
    {
        "ats_data":     dict | None,
        "resume_bytes": bytes | None,
        "github_url":   str  | None,
    }

If all three keys are None/empty for a slot, that slot is skipped.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Callable, Optional, TypedDict

from app.models.candidate import CanonicalCandidate
from app.services.transformer_service import TransformerService
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class CandidateSlot(TypedDict, total=False):
    """Input specification for one candidate in a batch."""
    ats_data:     Optional[dict[str, Any]]
    resume_bytes: Optional[bytes]
    github_url:   Optional[str]


class BatchResult(TypedDict):
    """Output for one processed candidate."""
    label:     str                   # human-readable label for the history panel
    canonical: CanonicalCandidate    # fully merged profile
    errors:    list[dict]            # parse / validation warnings
    index:     int                   # original slot index (0-based)
    status:    str                   # "ok" | "error" | "skipped"
    error_msg: Optional[str]         # set when status == "error"


# ---------------------------------------------------------------------------
# BatchService
# ---------------------------------------------------------------------------

class BatchService:
    """Thin orchestrator that processes multiple candidates in one call.

    Args:
        service: An initialised (and optionally cached) TransformerService.
    """

    def __init__(self, service: TransformerService) -> None:
        self._service = service

    def run(
        self,
        slots: list[CandidateSlot],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[BatchResult]:
        """Process all candidate slots sequentially.

        Args:
            slots:       List of CandidateSlot dicts (one per candidate).
            on_progress: Optional callback(done, total, label) for UI progress.

        Returns:
            List of BatchResult dicts, one per non-skipped slot.
        """
        results: list[BatchResult] = []
        total = len(slots)

        for idx, slot in enumerate(slots):
            ats_data     = slot.get("ats_data")
            resume_bytes = slot.get("resume_bytes")
            github_url   = slot.get("github_url") or None

            missing_inputs = []
            if not ats_data:
                missing_inputs.append("ATS JSON")
            if not resume_bytes:
                missing_inputs.append("Resume PDF")
            if not github_url or not github_url.strip():
                missing_inputs.append("GitHub Profile URL")

            if missing_inputs:
                label_hint = (
                    (ats_data or {}).get("full_name")
                    or (ats_data or {}).get("name")
                    or f"Candidate {idx + 1}"
                )
                msg = f"Missing: {', '.join(missing_inputs)}"
                logger.warning("Slot %d (%s) skipped: %s", idx + 1, label_hint, msg)
                if on_progress:
                    on_progress(idx + 1, total, f"#{idx + 1} — skipped ({msg})")
                results.append(BatchResult(
                    label=f"#{idx + 1} · {label_hint} (Skipped)",
                    canonical=None,    # type: ignore[arg-type]
                    errors=[],
                    index=idx,
                    status="skipped",
                    error_msg=msg,
                ))
                continue

            label_hint = (
                (ats_data or {}).get("full_name")
                or (ats_data or {}).get("name")
                or f"Candidate {idx + 1}"
            )
            logger.info("Processing slot %d/%d: %s", idx + 1, total, label_hint)

            if on_progress:
                on_progress(idx + 1, total, f"#{idx + 1} — {label_hint}")

            try:
                resume_io = io.BytesIO(resume_bytes) if resume_bytes else None
                canonical, _projected, errors = self._service.transform(
                    ats_data=ats_data,
                    resume_source=resume_io,
                    github_url=github_url,
                    output_config=None,
                )

                # Build display label
                run_num  = len(results) + 1
                name     = canonical.full_name or label_hint
                short_id = canonical.candidate_id[:8]
                label    = f"#{run_num} · {name} ({short_id})"

                results.append(BatchResult(
                    label=label,
                    canonical=canonical,
                    errors=errors,
                    index=idx,
                    status="ok",
                    error_msg=None,
                ))

            except Exception as exc:
                msg = f"Pipeline error for slot {idx + 1}: {exc}"
                logger.error(msg, exc_info=True)
                results.append(BatchResult(
                    label=f"#{idx + 1} — ERROR",
                    canonical=None,    # type: ignore[arg-type]
                    errors=[],
                    index=idx,
                    status="error",
                    error_msg=msg,
                ))

        logger.info(
            "Batch complete — %d processed, %d errors.",
            sum(1 for r in results if r["status"] == "ok"),
            sum(1 for r in results if r["status"] == "error"),
        )
        return results


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def run_batch(
    service: TransformerService,
    slots: list[CandidateSlot],
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> list[BatchResult]:
    """Module-level convenience wrapper around BatchService.run()."""
    return BatchService(service).run(slots, on_progress=on_progress)
