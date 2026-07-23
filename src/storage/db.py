"""SQLite storage: connection helper and schema initialization.

Holds the structured stores from PLAN.md §4.2:
  - jobs          : normalized, extracted job postings
  - applications  : the user's kanban-style application pipeline
  - preferences   : the user's explicit search preferences (single row)

Embeddings live in ChromaDB (see ``vectors.py``), never here. This module is
the baseline schema; per CLAUDE.md, changes after Phase 1 require a migration
script under ``src/storage/migrations/``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config import SQLITE_PATH

# Application status values, kept in sync with the CHECK constraint below and
# with the ApplicationStatus enum used by the MCP tools (PLAN.md §4.4).
APPLICATION_STATUSES: tuple[str, ...] = (
    "interested",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS jobs (
    id               TEXT PRIMARY KEY,
    company          TEXT NOT NULL,
    role             TEXT NOT NULL,
    location         TEXT,
    remote_type      TEXT,               -- e.g. 'remote', 'hybrid', 'onsite'
    stack            TEXT,               -- JSON array of technologies
    experience_years INTEGER,
    salary_min       INTEGER,
    salary_max       INTEGER,
    posted_date      TEXT,               -- ISO-8601 date string
    description      TEXT,
    source           TEXT NOT NULL,      -- e.g. 'remoteok', 'wwr', 'hn'
    source_url       TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS applications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status     TEXT NOT NULL CHECK (status IN (
                   {", ".join(f"'{s}'" for s in APPLICATION_STATUSES)}
               )),
    notes      TEXT NOT NULL DEFAULT '',
    applied_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (job_id)
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);

-- Singleton row (id = 1) holding the user's explicit preferences.
CREATE TABLE IF NOT EXISTS preferences (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    min_salary        INTEGER,
    locations         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    remote_ok         INTEGER NOT NULL DEFAULT 1,    -- 0/1 boolean
    roles_of_interest TEXT NOT NULL DEFAULT '[]',   -- JSON array
    exclude_companies TEXT NOT NULL DEFAULT '[]',   -- JSON array
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection(db_path: Path = SQLITE_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults.

    Enables foreign-key enforcement (off by default in SQLite) and row access
    by column name. The caller is responsible for closing the connection.

    Args:
        db_path: Path to the SQLite database file. Defaults to the configured
            ``data/jobs.db``. The parent directory is created if missing.

    Returns:
        An open ``sqlite3.Connection``.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path = SQLITE_PATH) -> None:
    """Create all tables if they do not already exist.

    Idempotent — safe to call on every startup. Also seeds the singleton
    preferences row so downstream code can always assume it exists.

    Args:
        db_path: Path to the SQLite database file.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.execute("INSERT OR IGNORE INTO preferences (id) VALUES (1);")
        conn.commit()
    finally:
        conn.close()
