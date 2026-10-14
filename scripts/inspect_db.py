#!/usr/bin/env python
"""Inspect both stores after ingestion (Phase 1 sanity check).

Prints SQLite job counts + a few sample rows, the ChromaDB chunk count, and runs
one semantic query to confirm the vector path works end-to-end.

Usage:
    uv run python scripts/inspect_db.py
    uv run python scripts/inspect_db.py --query "python backend distributed systems"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.db import count_jobs, get_connection  # noqa: E402
from src.storage.vectors import get_jobs_collection  # noqa: E402


def show_sqlite(sample: int) -> None:
    """Print job count and a sample of rows from SQLite."""
    conn = get_connection()
    try:
        total = count_jobs(conn)
        print(f"\n[SQLite] jobs: {total}")
        rows = conn.execute(
            "SELECT company, role, stack, experience_years, salary_min, salary_max "
            "FROM jobs ORDER BY created_at DESC LIMIT ?;",
            (sample,),
        ).fetchall()
        for r in rows:
            stack = ", ".join(json.loads(r["stack"])[:5])
            exp = f"{r['experience_years']}y" if r["experience_years"] is not None else "?"
            salary = f"${r['salary_min']}-{r['salary_max']}" if r["salary_min"] else "salary n/a"
            print(f"  - {r['role']} @ {r['company']} | exp {exp} | {salary} | [{stack}]")
    finally:
        conn.close()


def show_chroma(query: str) -> None:
    """Print chunk count and the top semantic matches for ``query``."""
    collection = get_jobs_collection()
    print(f"\n[ChromaDB] chunks: {collection.count()}")
    if collection.count() == 0:
        return
    results = collection.query(query_texts=[query], n_results=3)
    print(f'  query: "{query}"')
    for doc, meta in zip(results["documents"][0], results["metadatas"][0], strict=False):
        print(f"  - ({meta['job_id']}) {doc[:80].strip()}...")


def main() -> int:
    """Parse args and print both stores' state."""
    parser = argparse.ArgumentParser(description="Inspect the job stores.")
    parser.add_argument("--sample", type=int, default=5, help="SQLite rows to show.")
    parser.add_argument(
        "--query",
        default="python backend engineer",
        help="Semantic query to test the vector store.",
    )
    args = parser.parse_args()

    show_sqlite(args.sample)
    show_chroma(args.query)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
