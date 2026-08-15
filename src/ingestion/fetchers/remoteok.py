"""RemoteOK fetcher — the first ingestion source (PLAN.md §9: cleanest API).

Fetches the public RemoteOK JSON feed and writes it verbatim to the raw
("bronze") layer as JSONL, one record per line. Downstream stages read from the
returned records; the raw file exists so normalization/extraction can be
replayed offline without re-hitting the API (which matters under free-tier
rate limits).

Uses stdlib ``urllib`` — a single GET doesn't warrant an HTTP-client dependency.
"""

from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path
from typing import Any

from src.config import RAW_DIR, REMOTEOK_API_URL

# RemoteOK rejects the default urllib user-agent; a browser-like UA is required.
_USER_AGENT = "Mozilla/5.0 (compatible; job-search-agent/0.1; +local)"


def fetch_remoteok(raw_dir: Path = RAW_DIR, today: str | None = None) -> list[dict[str, Any]]:
    """Fetch RemoteOK jobs and persist the raw payload to ``raw_dir``.

    Args:
        raw_dir: Directory for the raw JSONL output. Created if missing.
        today: ISO date string for the filename; defaults to today's date.

    Returns:
        The list of raw job records (the API's leading legal-notice entry, which
        has no ``id``, is filtered out).
    """
    today = today or datetime.date.today().isoformat()
    request = urllib.request.Request(REMOTEOK_API_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - trusted URL
        payload = json.loads(response.read().decode("utf-8"))

    # The first element is a legal notice, not a job; real jobs carry an "id".
    jobs = [r for r in payload if isinstance(r, dict) and r.get("id")]

    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"remoteok_{today}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for record in jobs:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return jobs
