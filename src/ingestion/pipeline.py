"""Ingestion orchestrator: fetch → normalize → dedup → enrich → chunk → persist.

Ties the ingestion stages together and writes to both stores (PLAN.md Flow A):
  - SQLite ``jobs``          : one structured row per unique job
  - ChromaDB ``jobs``        : embedded description chunks, joined by ``job_id``

The raw ("bronze") layer is written by the fetcher before this runs, so the
whole flow after fetch can be replayed offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import structlog

from src.config import DEFAULT_INGEST_LIMIT
from src.ingestion.chunker import chunk_job
from src.ingestion.deduper import dedupe
from src.ingestion.extractor import enrich_job
from src.ingestion.fetchers.remoteok import fetch_remoteok
from src.ingestion.normalizer import NormalizedJob, normalize_remoteok
from src.storage.db import count_jobs, get_connection, init_db, insert_job, job_exists
from src.storage.vectors import get_jobs_collection, upsert_job_chunks

log = structlog.get_logger(__name__)


@dataclass
class IngestionStats:
    """Counts describing one ingestion run."""

    fetched: int = 0
    normalized: int = 0
    deduped: int = 0
    enriched: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    chunks_embedded: int = 0
    total_jobs_in_db: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return the stats as a plain dict."""
        return asdict(self)


def run_ingestion(
    limit: int = DEFAULT_INGEST_LIMIT,
    enrich: bool = True,
) -> IngestionStats:
    """Run the full RemoteOK ingestion flow and return run statistics.

    Args:
        limit: Maximum number of (deduped) jobs to persist this run.
        enrich: If True, call the LLM to fill gaps (e.g. experience_years) on
            jobs that need it. If False, skip all LLM calls (fast, zero quota).

    Returns:
        An ``IngestionStats`` summarizing the run.
    """
    stats = IngestionStats()
    init_db()

    log.info("fetch_start", source="remoteok")
    raw_records = fetch_remoteok()
    stats.fetched = len(raw_records)

    normalized: list[NormalizedJob] = [
        job for r in raw_records if (job := normalize_remoteok(r)) is not None
    ]
    stats.normalized = len(normalized)

    deduped = dedupe(normalized)
    stats.deduped = len(deduped)

    batch = deduped[:limit]
    log.info("processing", candidates=len(batch), enrich=enrich)

    conn = get_connection()
    collection = get_jobs_collection()
    try:
        for job in batch:
            # Skip jobs already stored BEFORE spending an LLM call on them.
            if job_exists(conn, job.source_url):
                stats.skipped_existing += 1
                continue

            if enrich:
                before = job.experience_years
                job = enrich_job(job)
                if job.experience_years != before:
                    stats.enriched += 1

            _insert_and_index(conn, collection, job, stats)
        conn.commit()
        stats.total_jobs_in_db = count_jobs(conn)
    finally:
        conn.close()

    log.info("ingestion_complete", **stats.as_dict())
    return stats


def _insert_and_index(conn, collection, job: NormalizedJob, stats: IngestionStats) -> None:
    """Persist one (known-new) job to SQLite and embed its chunks into ChromaDB.

    Callers must have already confirmed the job is new (see ``job_exists``), so
    the SQLite insert and the vector index stay in lockstep.
    """
    if not insert_job(conn, job.to_row()):
        # Extremely unlikely given the prior job_exists check, but stay honest.
        stats.skipped_existing += 1
        return
    stats.inserted += 1
    chunks = chunk_job(job)
    stats.chunks_embedded += upsert_job_chunks(
        collection, job.id, chunks, base_metadata={"source": job.source}
    )
