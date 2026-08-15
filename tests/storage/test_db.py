"""Integration tests for the SQLite store (against a temp DB)."""

from __future__ import annotations

from pathlib import Path

from src.ingestion.normalizer import NormalizedJob
from src.storage.db import count_jobs, get_connection, init_db, insert_job


def _job(job_id: str = "remoteok:1", url: str = "https://x/1") -> dict:
    return NormalizedJob(
        id=job_id,
        company="Acme",
        role="Backend Engineer",
        stack=["python", "postgres"],
        source="remoteok",
        source_url=url,
    ).to_row()


def test_insert_and_count(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    init_db(db)
    conn = get_connection(db)
    try:
        assert insert_job(conn, _job()) is True
        conn.commit()
        assert count_jobs(conn) == 1
    finally:
        conn.close()


def test_insert_is_idempotent_on_source_url(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    init_db(db)
    conn = get_connection(db)
    try:
        assert insert_job(conn, _job(url="https://x/dup")) is True
        # Same source_url, different id → INSERT OR IGNORE returns False, no dup row.
        assert insert_job(conn, _job(job_id="remoteok:2", url="https://x/dup")) is False
        conn.commit()
        assert count_jobs(conn) == 1
    finally:
        conn.close()


def test_preferences_singleton_seeded(tmp_path: Path) -> None:
    db = tmp_path / "jobs.db"
    init_db(db)
    conn = get_connection(db)
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM preferences;").fetchone()
        assert row["n"] == 1  # singleton row seeded by init_db
    finally:
        conn.close()
