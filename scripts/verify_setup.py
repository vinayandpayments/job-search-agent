#!/usr/bin/env python
"""Phase 0 verification — proves the whole stack is wired.

Runs three checks end-to-end and prints a summary:
  1. SQLite  : init schema, insert a fake job, read it back.
  2. ChromaDB: embed a string locally (MiniLM), add + query the collection.
  3. Gemini  : call gemini-2.5-flash with a trivial prompt.

Run with:  uv run python scripts/verify_setup.py

This is the Phase 0 Definition of Done (PLAN.md §6).
"""

from __future__ import annotations

import sys

# Make `src` importable when run as a plain script from the repo root.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.config import EXTRACTION_MODEL, get_settings  # noqa: E402
from src.llm.client import generate_text  # noqa: E402
from src.storage.db import get_connection, init_db  # noqa: E402
from src.storage.vectors import get_jobs_collection  # noqa: E402

FAKE_JOB_ID = "verify-0001"


def check_sqlite() -> str:
    """Init the DB, insert a fake job, read it back. Returns a status line."""
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM jobs WHERE id = ?;", (FAKE_JOB_ID,))
        conn.execute(
            """
            INSERT INTO jobs (id, company, role, source, source_url)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                FAKE_JOB_ID,
                "Acme Corp",
                "Senior Backend Engineer",
                "verify",
                f"https://example.com/{FAKE_JOB_ID}",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT company, role FROM jobs WHERE id = ?;", (FAKE_JOB_ID,)
        ).fetchone()
    finally:
        # Clean up so repeated runs stay idempotent.
        conn.execute("DELETE FROM jobs WHERE id = ?;", (FAKE_JOB_ID,))
        conn.commit()
        conn.close()
    return f"SQLite   : inserted + read back job → {row['role']} @ {row['company']}"


def check_chromadb() -> str:
    """Embed a string locally and query it back. Returns a status line."""
    collection = get_jobs_collection()
    collection.upsert(
        ids=[FAKE_JOB_ID],
        documents=["Senior backend engineer working on distributed systems in Python."],
        metadatas=[{"source": "verify"}],
    )
    results = collection.query(query_texts=["python backend role"], n_results=1)
    nearest = results["documents"][0][0]
    collection.delete(ids=[FAKE_JOB_ID])  # keep the store clean
    return f"ChromaDB : embedded locally + nearest match → {nearest[:48]}..."


def check_gemini() -> str:
    """Call Gemini with a trivial prompt. Returns a status line."""
    reply = generate_text(prompt="Reply with exactly the word: OK", model=EXTRACTION_MODEL)
    return f"Gemini   : {EXTRACTION_MODEL} responded → {reply!r}"


def main() -> int:
    """Run all checks; return 0 on success, 1 on any failure."""
    settings = get_settings()
    if not settings.gemini_api_key:
        print("❌ GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
        return 1

    checks = (
        ("SQLite", check_sqlite),
        ("ChromaDB", check_chromadb),
        ("Gemini", check_gemini),
    )
    for name, fn in checks:
        try:
            print("  " + fn())
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            print(f"❌ {name} check failed: {exc}")
            return 1

    print("\n✅ Phase 0 verified: SQLite + ChromaDB + Gemini all working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
