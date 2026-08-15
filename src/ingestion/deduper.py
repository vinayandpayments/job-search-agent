"""Deduplication within an ingestion batch.

Removes duplicate postings by the key ``(company, role, source_url)`` (PLAN.md
Flow A step 3). This handles same-run duplicates; cross-run duplicates are
caught separately by the UNIQUE(source_url) constraint in SQLite.

Company and role are compared case-insensitively; ``source_url`` is exact.
"""

from __future__ import annotations

from src.ingestion.normalizer import NormalizedJob


def _dedup_key(job: NormalizedJob) -> tuple[str, str, str]:
    return (job.company.strip().lower(), job.role.strip().lower(), job.source_url.strip())


def dedupe(jobs: list[NormalizedJob]) -> list[NormalizedJob]:
    """Return the batch with duplicates removed, preserving first-seen order.

    Args:
        jobs: Normalized jobs, possibly containing duplicates.

    Returns:
        A new list containing the first occurrence of each unique job.
    """
    seen: set[tuple[str, str, str]] = set()
    unique: list[NormalizedJob] = []
    for job in jobs:
        key = _dedup_key(job)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique
