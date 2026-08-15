# CLAUDE.md

Instructions for Claude Code when working on this repository. Read this file at the start of every session.

---

## Project Context

This is the **Personal Job Search Agent** — an agentic AI system that ingests job postings and helps a single user find, evaluate, and apply to jobs. Full context is in `PLAN.md`. Read `PLAN.md` before making architectural changes; it contains the reasoning behind every non-obvious choice.

**The user (Vinay) is building this to learn agentic AI engineering deeply.** He is not looking for the fastest solution — he is looking for the *right* solution, with reasoning he can defend in an interview. When you propose code, prioritize clarity of design over cleverness.

---

## Core Principles (in priority order)

1. **Understand before you write.** If a task touches an area not covered in `PLAN.md`, pause and ask before generating code. Do not invent architectural decisions silently.
2. **Prefer standard library and hand-written primitives over frameworks.** The learning goal requires seeing what frameworks abstract. Do not introduce LangChain chains, agents, or memory abstractions without explicit user approval. LangChain's document loaders and text splitters are pre-approved (see PLAN.md §4.6).
3. **Every LLM call is a design decision.** State which model, why that model, whether it's cached, and what tokens go in. Do not add LLM calls without justification.
4. **Structured outputs whenever possible.** Any LLM call that produces data (not user-facing prose) must return schema-validated JSON via tool use or structured output mode. Use pydantic models.
5. **Evaluation is a deliverable, not an afterthought.** New tools, new memory logic, and new prompts all require corresponding entries in `evals/test_set.yaml`.

---

## Code Style and Structure

### Python
- **Version:** 3.11+
- **Type hints:** required on all function signatures, dataclass fields, and pydantic models
- **Formatter:** `ruff format`
- **Linter:** `ruff check --fix`
- **Package manager:** `uv` (not pip, not poetry)
- **Testing:** `pytest`, with test files mirroring `src/` structure under `tests/`
- **Docstrings:** required on all public functions and classes; single-line for simple functions, multi-line with Args/Returns for anything non-obvious
- **Async:** prefer async throughout the API and agent layers; sync is fine for ingestion scripts

### File organization
- One responsibility per module. If a file exceeds ~300 lines, propose a split.
- Import order: stdlib, third-party, local. Enforced by ruff.
- No circular imports — if you hit one, the boundary is wrong.

### Naming
- `snake_case` for functions, variables, module names
- `PascalCase` for classes and pydantic models
- `SCREAMING_SNAKE_CASE` for constants
- Prefer descriptive names over short ones; `application_status` beats `app_stat`

---

## Architectural Rules (non-negotiable without discussion)

- **Two stores, never one:** SQLite for structured job data + application state; ChromaDB for embeddings. Never store embeddings in SQLite or structured facts in ChromaDB metadata alone.
- **Memory tiers are separate modules:** `src/memory/persistent.py`, `src/memory/working.py`, `src/memory/summarizer.py`. Do not merge them or add memory logic outside `src/memory/`.
- **The agent loop is hand-written in `src/agent/loop.py`.** Do not replace it with a LangChain agent, LangGraph graph, or any other framework abstraction without explicit approval.
- **MCP tools live in `src/mcp_server/tools/`, one file per tool.** Tool descriptions live inline with the tool definition and must be updated in tandem with any behavior change.
- **All LLM (Gemini) API calls go through `src/llm/client.py`.** This is the only place where model names, caching config, and API keys are referenced. Do not scatter `genai` / `client.models.generate_content` calls across the codebase.
- **All prompts live in `src/agent/prompts.py` or `src/llm/extraction.py`.** No inline prompt strings in business logic.

---

## LLM Usage Rules

> **Provider:** Primary LLM is **Google Gemini** via the `google-genai` SDK (no Anthropic key available). A Grok/xAI key exists but is deferred as a fallback — do not wire it without asking. See PLAN.md §4.3 and §9.

### Model selection (see PLAN.md §4.3 for full table)
Concrete model IDs are defined **once** in `src/config.py` — refer to it, don't hard-code names elsewhere. Current mapping (Day 0, free-tier key):
- **Ingestion extraction:** Gemini Flash-lite (`EXTRACTION_MODEL`)
- **Agent loop, cover letters, fit analysis:** `AGENT_MODEL` (a Flash model) — the free-tier key has no Pro quota and billing is intentionally OFF; if Flash quality lags, the fallback is a free/open-source model (e.g. Ollama), not paid Pro. Do not add billing without asking.
- **Session summarization:** Gemini Flash-lite (`SUMMARY_MODEL`)
- **Embeddings:** local `sentence-transformers/all-MiniLM-L6-v2` — no API calls for embeddings

If you propose a different model for a task, justify it in the same message.

### Prompt caching
- System prompt + tool definitions + user profile summary form the stable prefix on every agent call. This should be cached.
- **Gemini caching differs from Anthropic's.** Gemini uses explicit `CachedContent` (with a minimum-token threshold) plus implicit caching on some models — it is not automatic prefix caching. The concrete mechanism is **deferred to Phase 3**, when the stable prefix actually exists.
- Tool results and conversation tail vary — do not cache these.
- When adding a new field to the stable prefix, verify it does not vary per-call (or caching breaks).

### Cost discipline
- Any change that adds an LLM call to a per-query path must be flagged in the PR message.
- Extraction during ingestion runs on every chunk — schema changes that increase output tokens meaningfully should be flagged.

---

## Data and Storage Rules

- **Never commit `data/user/`** — resume and profile are personal.
- **Never commit `data/chroma/` or `data/jobs.db`** — data files, gitignored.
- **Never commit `.env`** — only `.env.example` with placeholder values.
- **Schema changes require a migration script** in `src/storage/migrations/`. Do not edit `db.py`'s CREATE TABLE statements after Phase 1 without a migration.
- **Test data lives in `tests/fixtures/`** — small, hand-curated, committed.

---

## Testing Expectations

- **Unit tests** for pure logic: normalizer, deduper, chunker, memory summarizer, filter parsing
- **Integration tests** for anything touching storage: ingestion pipeline end-to-end with fixture data, memory persistence round-trips
- **Agent-level tests** live in `evals/`, not `tests/` — they are eval, not unit tests
- Every PR that changes behavior must update or add tests; if you're unsure whether it counts as a behavior change, ask.

---

## Working Loop Expectations

When given a task, this is the expected flow:

1. **Restate the task** in your own words before starting, especially if it's non-trivial.
2. **Identify affected files** and any principles or architectural rules that apply.
3. **Discuss before code — with the user, not just in prose.** For module work (PLAN.md §6) this is mandatory: open with a concept walkthrough of the internals, present the decision menu with tradeoffs, and wait for Vinay's call on non-trivial forks. See PLAN.md "Working Agreement". Code lands only in small, explainable increments after decisions.
4. **Write the code** with clear commit-sized boundaries.
5. **Update `PLAN.md`'s Decisions Log** if a non-obvious choice was made.
6. **Update or add evals** if agent behavior, tools, or prompts changed.
7. **Summarize what changed and why** at the end.

For small tasks (e.g., "add a docstring", "fix a typo"), skip steps 1–3 and just do it.

---

## Things to Ask About, Not Assume

- Adding a new dependency
- Adding a new LLM call to a per-query path
- Changing a model choice
- Changing a database schema
- Changing tool descriptions (these affect agent behavior in subtle ways)
- Any architectural rule marked non-negotiable above

---

## Things You Can Do Freely

- Refactor within a module for clarity
- Add tests
- Improve docstrings and type hints
- Fix bugs with clear root causes
- Add logging (structured, via `structlog`)
- Rename local variables for clarity

---

## When Stuck

- If a design decision isn't in `PLAN.md` and isn't obvious, stop and ask.
- If two rules conflict, surface the conflict — don't silently resolve it.
- If a task requires touching something marked non-negotiable, propose the change and wait for approval.

---

## Vinay's Working Preferences

- Concept-first explanations before code, when introducing a new pattern
- Honest tradeoff analysis over "best practice" claims
- Willing to be pushed back on if the plan is wrong — say so directly
- Prefers depth on fewer things over shallow coverage of many
