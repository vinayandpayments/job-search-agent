"""Extraction orchestration (the ingestion side of map-first enrichment).

The map-first strategy (PLAN.md §4.3 note): fetchers map the structured fields a
source already provides; this stage only calls the LLM to fill *gaps*. For
RemoteOK the recurring gap is ``experience_years`` (never in the feed), inferred
from the description.

The prompt and output schema live in ``src.llm.extraction``; this module decides
*which* jobs need a call and applies the result. Skipping jobs that need no
enrichment is what keeps LLM cost — and free-tier quota use — near zero.
"""

from __future__ import annotations

import structlog

from src.ingestion.normalizer import NormalizedJob
from src.llm.extraction import extract_job_gaps

log = structlog.get_logger(__name__)


def needs_enrichment(job: NormalizedJob) -> bool:
    """Return True if the job is missing fields worth an LLM call.

    Currently: an unknown ``experience_years`` and a non-trivial description to
    infer it from. No description → nothing to extract → skip.
    """
    return job.experience_years is None and len(job.description) > 50


def enrich_job(job: NormalizedJob) -> NormalizedJob:
    """Fill a single job's gaps via the LLM, if it has any.

    Returns the job unchanged when no enrichment is needed or when the call
    fails (extraction is best-effort — a failure must not abort ingestion).

    Args:
        job: The normalized job to enrich.

    Returns:
        A possibly-updated copy of the job.
    """
    if not needs_enrichment(job):
        return job
    try:
        gaps = extract_job_gaps(job.role, job.company, job.description)
    except Exception as exc:  # noqa: BLE001 - best-effort; log and move on
        log.warning("enrichment_failed", job_id=job.id, error=str(exc))
        return job
    return job.model_copy(update={"experience_years": gaps.experience_years})
