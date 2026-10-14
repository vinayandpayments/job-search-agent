# Personal Job Search Agent

An agentic AI system that ingests public job postings and helps a single user find,
evaluate, and apply to jobs. See [PLAN.md](PLAN.md) for the full architecture and
[CLAUDE.md](CLAUDE.md) for engineering conventions.

**Primary LLM:** Google Gemini (2.5 Flash for cheap tasks, 2.5 Pro for the agent loop).
**Storage:** SQLite (structured job/application data) + ChromaDB (embeddings).
**Embeddings:** local `sentence-transformers/all-MiniLM-L6-v2` — no API cost.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
# 1. Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Pin Python and install dependencies
uv python pin 3.12
uv sync

# 3. Configure your API key
cp .env.example .env
# then edit .env and paste your GEMINI_API_KEY
```

## Verify the setup (Phase 0)

Runs a hello-world across the whole stack: inserts a fake job into SQLite, embeds a
string into ChromaDB, and calls Gemini with a test prompt.

```bash
uv run python scripts/verify_setup.py
```

A ✅ summary means Phase 0 is done.

## Project status

Phase 0 (foundations) complete. See PLAN.md §6 for the phased roadmap.
