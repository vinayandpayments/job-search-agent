"""Normalization: map a source's raw payload into one unified job format.

``NormalizedJob`` is the canonical internal representation of a job — the
contract every fetcher must produce and every downstream stage (dedup, chunk,
extract, persist) consumes. Source-specific mapping functions live here, one
per source.

The model mirrors the SQLite ``jobs`` schema (see ``storage/db.py``); ``to_row``
produces a dict ready for insertion.
"""

from __future__ import annotations

import html
import re
from typing import Any

from pydantic import BaseModel, Field

# Match HTML tags for stripping RemoteOK's HTML descriptions to plain text.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n\s*\n\s*\n+")


class NormalizedJob(BaseModel):
    """A single job in the unified internal format."""

    id: str  # stable, source-prefixed, e.g. "remoteok:123456"
    company: str
    role: str
    location: str | None = None
    remote_type: str | None = None  # 'remote' | 'hybrid' | 'onsite'
    stack: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    posted_date: str | None = None  # ISO-8601 date string
    description: str = ""
    source: str = ""
    source_url: str = ""

    def to_row(self) -> dict[str, Any]:
        """Return a dict matching the SQLite ``jobs`` columns.

        ``stack`` is left as a Python list; ``storage.db.insert_job`` serializes
        it to JSON. Keeping serialization at the storage boundary keeps this
        model storage-agnostic.
        """
        return self.model_dump()


def _html_to_text(raw: str | None) -> str:
    """Strip HTML tags and unescape entities into readable plain text."""
    if not raw:
        return ""
    text = _TAG_RE.sub("", raw)
    text = html.unescape(text)
    # Collapse runs of blank lines left behind by stripped block tags.
    return _WS_RE.sub("\n\n", text).strip()


def normalize_remoteok(raw: dict[str, Any]) -> NormalizedJob | None:
    """Map one RemoteOK API record into a ``NormalizedJob``.

    RemoteOK is already well-structured, so this is mostly direct field mapping;
    the description is HTML and gets flattened to text. Returns ``None`` for
    records missing the essentials (used to skip the API's leading legal-notice
    entry and any malformed rows).

    Args:
        raw: One decoded RemoteOK job object.

    Returns:
        A ``NormalizedJob``, or ``None`` if the record isn't a usable job.
    """
    job_id = raw.get("id")
    company = (raw.get("company") or "").strip()
    role = (raw.get("position") or "").strip()
    url = (raw.get("url") or "").strip()
    if not job_id or not company or not role or not url:
        return None

    salary_min = raw.get("salary_min") or None
    salary_max = raw.get("salary_max") or None

    return NormalizedJob(
        id=f"remoteok:{job_id}",
        company=company,
        role=role,
        location=(raw.get("location") or "").strip() or None,
        remote_type="remote",  # RemoteOK is remote-only by definition
        stack=[t.strip() for t in raw.get("tags", []) if isinstance(t, str) and t.strip()],
        salary_min=int(salary_min) if salary_min else None,
        salary_max=int(salary_max) if salary_max else None,
        posted_date=(raw.get("date") or "")[:10] or None,  # ISO timestamp -> date
        description=_html_to_text(raw.get("description")),
        source="remoteok",
        source_url=url,
    )
