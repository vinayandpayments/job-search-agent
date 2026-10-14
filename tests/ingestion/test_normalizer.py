"""Unit tests for RemoteOK normalization."""

from __future__ import annotations

from src.ingestion.normalizer import _html_to_text, normalize_remoteok

_RAW = {
    "id": "123456",
    "company": "Acme Corp",
    "position": "Senior Backend Engineer",
    "tags": ["python", "postgres", ""],
    "location": "Worldwide",
    "date": "2026-07-20T12:00:00+00:00",
    "url": "https://remoteok.com/remote-jobs/123456",
    "salary_min": 120000,
    "salary_max": 160000,
    "description": "<p>Build <b>distributed</b> systems.</p>",
}


def test_normalize_maps_core_fields() -> None:
    job = normalize_remoteok(_RAW)
    assert job is not None
    assert job.id == "remoteok:123456"
    assert job.company == "Acme Corp"
    assert job.role == "Senior Backend Engineer"
    assert job.source == "remoteok"
    assert job.remote_type == "remote"
    assert job.salary_min == 120000 and job.salary_max == 160000
    assert job.posted_date == "2026-07-20"  # ISO timestamp truncated to date


def test_normalize_strips_empty_tags_and_html() -> None:
    job = normalize_remoteok(_RAW)
    assert job is not None
    assert job.stack == ["python", "postgres"]  # empty tag dropped
    assert "<" not in job.description
    assert "distributed systems" in job.description


def test_normalize_rejects_incomplete_records() -> None:
    # Missing id (RemoteOK's leading legal-notice entry looks like this).
    assert normalize_remoteok({"company": "X", "position": "Y", "url": "u"}) is None
    # Missing company.
    assert normalize_remoteok({"id": "1", "position": "Y", "url": "u"}) is None


def test_html_to_text_unescapes_entities() -> None:
    assert _html_to_text("<p>A&amp;B</p>") == "A&B"
    assert _html_to_text(None) == ""
