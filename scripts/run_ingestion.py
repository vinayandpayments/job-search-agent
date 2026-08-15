#!/usr/bin/env python
"""Run the ingestion pipeline from the CLI (Phase 1 entry point).

Examples:
    uv run python scripts/run_ingestion.py                 # 50 jobs, with enrichment
    uv run python scripts/run_ingestion.py --limit 25      # fewer jobs
    uv run python scripts/run_ingestion.py --no-enrich     # skip all LLM calls (fast)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEFAULT_INGEST_LIMIT  # noqa: E402
from src.ingestion.pipeline import run_ingestion  # noqa: E402


def main() -> int:
    """Parse args, run ingestion, print a summary."""
    parser = argparse.ArgumentParser(description="Ingest jobs from RemoteOK.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_INGEST_LIMIT,
        help=f"Max jobs to persist (default: {DEFAULT_INGEST_LIMIT}).",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip LLM gap-filling (no API calls; fast).",
    )
    args = parser.parse_args()

    stats = run_ingestion(limit=args.limit, enrich=not args.no_enrich)

    print("\n=== Ingestion summary ===")
    for key, value in stats.as_dict().items():
        print(f"  {key:20s}: {value}")
    print("=========================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
