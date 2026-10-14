"""Unit tests for batch deduplication."""

from __future__ import annotations

from src.ingestion.deduper import dedupe
from src.ingestion.normalizer import NormalizedJob


def _job(job_id: str, company: str, role: str, url: str) -> NormalizedJob:
    return NormalizedJob(id=job_id, company=company, role=role, source_url=url)


def test_dedupe_removes_case_insensitive_duplicates() -> None:
    jobs = [
        _job("1", "Acme", "Backend Engineer", "https://x/1"),
        _job("2", "ACME", "backend engineer", "https://x/1"),  # same key, diff case
    ]
    result = dedupe(jobs)
    assert len(result) == 1
    assert result[0].id == "1"  # first occurrence kept


def test_dedupe_keeps_distinct_jobs() -> None:
    jobs = [
        _job("1", "Acme", "Backend Engineer", "https://x/1"),
        _job("2", "Acme", "Frontend Engineer", "https://x/2"),  # different role + url
    ]
    assert len(dedupe(jobs)) == 2


def test_dedupe_preserves_order() -> None:
    jobs = [
        _job("1", "A", "R", "https://x/1"),
        _job("2", "B", "R", "https://x/2"),
        _job("3", "A", "R", "https://x/1"),  # dup of #1
    ]
    result = dedupe(jobs)
    assert [j.id for j in result] == ["1", "2"]
