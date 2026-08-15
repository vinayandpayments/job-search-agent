"""Unit tests for job chunking."""

from __future__ import annotations

from src.ingestion.chunker import chunk_job
from src.ingestion.normalizer import NormalizedJob


def _job(description: str) -> NormalizedJob:
    return NormalizedJob(
        id="remoteok:1", company="Acme", role="Backend Engineer", description=description
    )


def test_chunk_job_always_returns_at_least_one_chunk() -> None:
    # Empty description → still one chunk (the header), so every job is indexed.
    chunks = chunk_job(_job(""))
    assert len(chunks) >= 1
    assert "Backend Engineer @ Acme" in chunks[0]


def test_chunk_job_includes_header_context() -> None:
    chunks = chunk_job(_job("We build distributed systems in Python."))
    assert "Backend Engineer @ Acme" in chunks[0]
    assert "distributed systems" in " ".join(chunks)


def test_chunk_job_splits_long_descriptions() -> None:
    long_text = "word " * 1000  # ~5000 chars, well past CHUNK_SIZE
    chunks = chunk_job(_job(long_text))
    assert len(chunks) > 1
