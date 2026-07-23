# PLAN.md — Personal Job Search Agent

> A portfolio-grade agentic AI system that helps a real user (initially: me) find, evaluate, and apply to jobs. Built to demonstrate deep, first-principles competence in context engineering, memory engineering, MCP/tool calling, inference engineering, and evaluation — the five skill areas required by production agentic AI roles.

---

## 1. Product Vision

**One-sentence pitch:** A personal AI agent that ingests job postings from public sources, maintains a rich profile of the user, and answers questions like *"What new backend roles this week fit my profile?"*, *"Draft a tailored cover letter for this role"*, *"What skills am I missing for senior MLE positions?"* — while learning from the user's feedback over time.

**Non-goals (explicit):**
- Not a job board — no listing UI as the primary experience; the chat/agent is the primary interface
- Not a scraper of paywalled sites (LinkedIn, Indeed direct scrape) — only public/free sources
- Not a general-purpose chatbot — it is narrowly a job-search agent with strong opinions
- Not multi-tenant SaaS in v1 — single-user, runs locally

**Primary user:** Me, actively job-hunting. This is critical: every day I use it, I generate real evaluation signal. The daily-use feedback loop is a design pillar, not an afterthought.

---

## 2. Why This Project (Skill Coverage Map)

Every JD skill area must be exercised deeply. This is the mapping:

| JD Skill Area | How This Project Exercises It |
|---|---|
| **Context Engineering** | Prompt composition juggling: user profile + preferences + retrieved jobs + conversation history + tool results, all competing for tokens. Prompt caching on stable prefixes (profile, tool defs). On-demand retrieval vs always-in-context tradeoffs for the user's resume. |
| **Memory Engineering** | Three-tier memory is *native* to the product: persistent (profile, application history, learned signals), working (current session state), retrieved (job chunks + structured job records). Not bolted on — designed in from day 1. |
| **Tool Design & MCP** | Custom MCP server exposing tools with real design tension (`search_jobs` vs `semantic_job_search` — the classic list-vs-search failure mode the JD tests on). Tool descriptions matter. Debugging tool selection is a real problem here, not a synthetic one. |
| **Inference Engineering** | Tiered model use: cheap model (Haiku) for extraction during ingestion, capable model (Sonnet) for the agent loop. Cost envelope managed and measured. Prompt caching on the tool definitions + system prompt saves real money over hundreds of daily queries. |
| **Evaluation Harness** | Test set of ~50 queries with known-correct behavior. Metrics: retrieval accuracy (are the right jobs returned?), citation accuracy (does every recommendation link to source?), fabrication refusal (does it say "I don't know" when it should?), preference-learning behavior (does it adapt after N feedback signals?). |

---

## 3. Architecture Overview

Two flows, run at different times, sharing storage.

### Flow A — Ingestion (offline, scheduled daily)

```
Public sources (RemoteOK API, WWR RSS, HN Who's Hiring)
        │
        ▼
[1] Fetcher (one per source)         → raw job posting JSON/HTML
        │
        ▼
[2] Normalizer                       → unified internal job format
        │
        ▼
[3] Deduper (by (company, role, source_url))
        │
        ▼
[4] Chunker (semantic-ish, by section)
        │
        ▼
[5] Structured extraction (Haiku, cheap model)
        │                            ↳ schema: company, role, location, remote_type,
        │                              stack[], experience_years, salary_range,
        │                              posted_date, description, source_url
        ▼
[6] Persist:
      ├── SQLite: jobs table + extracted structured facts
      └── ChromaDB: chunks + embeddings + metadata (job_id, section)
```

### Flow B — Query (online, per user interaction)

```
User message
    │
    ▼
[1] Agent loop (Claude Sonnet)
    │   context = system_prompt + tool_defs + user_profile_summary
    │             + working_memory + conversation_history + user_message
    │
    ▼
[2] Tool selection & call (via MCP)
    │
    ▼
[3] Tool executes:
      ├── search_jobs(filters)          → SQL against structured store
      ├── semantic_job_search(query, k) → ChromaDB similarity search
      ├── analyze_fit(job_id)           → LLM call comparing job vs profile
      ├── draft_cover_letter(job_id)    → LLM generation using profile + job
      ├── find_skill_gaps(target_role)  → aggregate query + LLM synthesis
      ├── track_application(job_id, status) → write to persistent store
      └── update_preferences(...)       → write to persistent store
    │
    ▼
[4] Agent evaluates tool result, decides: another tool call? synthesize?
    │
    ▼
[5] Final response with citations (every job mentioned links to source_url)
    │
    ▼
[6] Update working memory + persistent signals (user viewed/liked/rejected)
```

---

## 4. Design Decisions (with reasoning)

This section is the "why" behind every non-obvious choice. Revisit before changing anything here.

### 4.1 Storage: SQLite + ChromaDB, both local

**Decision:** SQLite for structured data, ChromaDB for vectors. Both file-based, both local.

**Why not Postgres?** No infra cost, no ops burden, portable (whole project is a folder). If we outgrow SQLite, the schema migrates cleanly.

**Why not just ChromaDB with metadata filters?** ChromaDB's metadata filtering works for simple `where` clauses but is not a real query engine — no joins, no aggregates, no complex boolean logic across relationships. Job search naturally has these ("companies I haven't applied to, with roles matching my stack, posted this week, with salary above X"). SQLite handles this cleanly.

**Why two stores at all instead of one?** Because the query profile is genuinely bimodal: precise filters ("Python roles > 120k in Bangalore") and semantic search ("roles like this one I liked"). One store can't serve both well. This is the core architectural insight of Project 1 in the JD applied here.

### 4.2 Memory Architecture (three tiers)

This is designed carefully because memory is where junior systems fall apart.

**Persistent memory** — survives across sessions, stored on disk:
- `user_profile`: parsed resume (structured), skills[], years_experience, education, past_projects
- `preferences`: explicit (min_salary, locations[], remote_ok, roles_of_interest[], exclude_companies[])
- `application_history`: {job_id, status, applied_at, notes} — kanban-style
- `feedback_signals`: implicit — jobs viewed, saved, rejected, dwell time; used to refine recommendations
- `learned_facts`: durable inferences ("user prefers early-stage over enterprise", "user avoids on-call heavy roles") — added by agent when patterns are strong

Storage: SQLite tables + a small JSON blob for learned_facts.

**Working memory** — lives only during a single conversation, in-memory:
- Current conversation turns (bounded, e.g., last 10)
- Current filter set the user has narrowed to
- Jobs currently being discussed (their IDs)
- Recently-called tools + their results (to avoid redundant calls in the same session)

Storage: Python dict/dataclass, keyed by session_id. Optionally backed by Redis if session persistence across process restarts is wanted (deferred to later phase).

**Retrieved memory** — pulled fresh per query:
- Chunks from ChromaDB matching the semantic aspects of the current query
- Rows from SQLite matching the structural filters
- Both scoped to a reasonable K to fit the context budget

**Key design rule:** persistent memory is *summarized* before entering the prompt. We never dump the full application history into context — instead, a compact summary ("user has applied to 12 backend roles in Bangalore, mostly rejected due to seniority mismatch") goes in. The full history is behind a tool call if needed.

**Why this matters:** context is finite and expensive. Persistent memory *appears* free but bloats prompts fast if you're careless. Summarization is the discipline that makes long-term memory usable.

### 4.3 Model Selection (Inference Engineering)

| Task | Model | Reason |
|---|---|---|
| Structured extraction during ingestion | Claude Haiku 4.5 | Schema-constrained JSON output, small model is enough, runs on every chunk |
| Embedding generation | `sentence-transformers/all-MiniLM-L6-v2` (local) | Free, fast, good enough for job descriptions; no API cost per embedding |
| Agent loop (tool calling + reasoning) | Claude Sonnet | Needs to reason about which tool to call, handle multi-step plans, refuse fabrication |
| Cover letter drafting | Claude Sonnet | Quality of output matters, this is user-facing content |
| Fit analysis (resume vs job) | Claude Sonnet | Nuanced comparison, worth the cost per call |
| Session summarization (compressing old turns) | Claude Haiku | Simple task, runs frequently |

**Cost envelope target:** under $2/day of personal use assuming ~50 messages/day.

**Caching strategy:** system prompt + tool definitions + user profile summary form a stable prefix on every agent call → these get prompt-cached. Only conversation tail + tool results vary. Expected cache hit rate on the stable portion: >90%.

### 4.4 MCP Server Design

Tools exposed via a custom MCP server (Python, using the official `mcp` SDK).

**Tool list with descriptions (draft):**

```
search_jobs(filters: JobFilters) -> list[Job]
  Description: "Search jobs by structured criteria (stack, location, salary, date range,
  remote type, seniority). Use this when the user's request can be expressed as filters
  on job attributes. Prefer this over semantic_job_search when the user names specific
  attributes. Returns up to 20 matching jobs with full metadata."

semantic_job_search(query: str, k: int = 5) -> list[Job]
  Description: "Search jobs by semantic similarity to a query string. Use this when the
  user's request is thematic or fuzzy ('roles like the one at Acme', 'jobs involving
  distributed systems') and cannot be reduced to concrete filters. Do NOT use this for
  filter-expressible queries — use search_jobs instead."

analyze_fit(job_id: str) -> FitAnalysis
  Description: "Compare the user's profile against a specific job posting. Returns match
  score, matching qualifications, gaps, and a summary. Call this after the user shows
  interest in a specific job."

draft_cover_letter(job_id: str, tone: str = 'professional') -> str
  Description: "Generate a tailored cover letter for a specific job using the user's
  profile. Tone can be 'professional', 'enthusiastic', 'concise'. Only call when the
  user explicitly asks for a cover letter."

find_skill_gaps(target_role: str) -> SkillGapReport
  Description: "Analyze what skills the user is missing for a target role type, based on
  aggregate patterns across jobs matching that role. Use when the user asks about career
  development or role transitions."

track_application(job_id: str, status: ApplicationStatus, notes: str = '') -> None
  Description: "Record that the user has applied to a job, or update the status of an
  existing application. Status values: 'interested', 'applied', 'interviewing',
  'offer', 'rejected', 'withdrawn'."

update_preferences(**kwargs) -> Preferences
  Description: "Update the user's stated preferences. Common fields: min_salary, locations,
  remote_ok, roles_of_interest, exclude_companies. Only call when the user explicitly states
  a preference change."

get_application_status() -> ApplicationSummary
  Description: "Retrieve a summary of the user's current applications, grouped by status.
  Use when the user asks about their pipeline or 'what have I applied to'."
```

**Design tension baked in intentionally:** `search_jobs` vs `semantic_job_search` is the classic failure mode. Descriptions must steer strongly. This is the exact debugging scenario the JD tests on — good, we'll live it.

**MCP server structure:**
- `mcp_server/` — the MCP server itself, launchable as a subprocess
- Tools defined as Python functions with type-annotated inputs
- Server exposes them over stdio (default MCP transport)
- Agent connects as an MCP client
- Same server can be plugged into Claude Desktop for manual testing — useful debugging

### 4.5 Evaluation Harness

Built alongside the system, not after. Evaluation is a deliverable.

**Test set structure** (`evals/test_set.yaml`):
- ~50 queries, categorized by intent (filter, semantic, fit-analysis, refusal, etc.)
- Each with expected behavior: which tool should be called, what kind of result is acceptable, what would count as a failure

**Metrics tracked:**

1. **Tool selection accuracy** — for each test query, did the agent pick the right tool? (measured against annotated expected tool)
2. **Retrieval precision@K** — of the jobs returned, what fraction actually match the stated criteria?
3. **Citation completeness** — does every job mentioned in the response have a source_url citation?
4. **Fabrication refusal rate** — for queries about non-existent data (fake company, fake role), does the system refuse instead of inventing?
5. **Preference-learning behavior** — after N synthetic feedback signals, does the ranking change appropriately?
6. **Cost per query** — mean tokens consumed, mean $ per query
7. **Latency** — mean time to first token, mean time to full response

**Eval runner** (`evals/run_evals.py`):
- Loads test set
- Runs each query through the agent (with a clean session, so no cross-contamination)
- Scores automatically where possible; flags for manual review where not (e.g., cover letter quality)
- Outputs a report with per-metric scores and regressions vs the previous run

**When to run evals:** before every commit that touches the agent loop, tool descriptions, or memory. Also as a nightly job.

### 4.6 Framework Choices

**LangChain — used sparingly:**
- `langchain-community` document loaders for parsing (PDF resume, HTML job pages) — saves boilerplate, low lock-in
- `RecursiveCharacterTextSplitter` for chunking — well-tuned defaults, low lock-in
- **Not used for:** the agent loop, memory abstractions, chains. Those are hand-written so we understand every token.

**LangGraph — deferred, evaluated after v1:**
- Once the hand-written agent loop works, evaluate whether LangGraph's state-machine model adds value for multi-step workflows (e.g., "search → filter → analyze fit → draft letter" as a graph).
- If yes, migrate the agent loop to LangGraph in v2. If no, note why in the decisions log.

**MCP SDK:** official Python `mcp` package. No alternatives worth considering.

**Anthropic SDK:** official `anthropic` Python SDK. Direct API calls, no wrapper.

**Vector store:** ChromaDB (already familiar to me, local, free).

**Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` locally (no API cost).

**Backend framework:** FastAPI (async, clean, good for streaming responses to the frontend).

**Frontend:** React + TypeScript + Vite. Chat UI + application tracker + profile editor. Deferred to Phase 4 — not needed to demonstrate agent quality.

---

## 5. Repo Structure

```
job-search-agent/
├── PLAN.md                  ← this file
├── CLAUDE.md                ← conventions and rules for Claude Code
├── README.md                ← user-facing setup instructions
├── pyproject.toml           ← Python deps (uv-managed)
├── .env.example             ← template for API keys
├── .gitignore
│
├── src/
│   ├── ingestion/
│   │   ├── fetchers/        ← one module per source (remoteok, wwr, hn_hiring)
│   │   ├── normalizer.py    ← unified job format
│   │   ├── deduper.py
│   │   ├── chunker.py
│   │   ├── extractor.py     ← LLM-based structured extraction
│   │   └── pipeline.py      ← orchestrates the full ingestion flow
│   │
│   ├── storage/
│   │   ├── db.py            ← SQLite schema + connection
│   │   ├── vectors.py       ← ChromaDB wrapper
│   │   └── migrations/
│   │
│   ├── memory/
│   │   ├── persistent.py    ← profile, preferences, history, learned_facts
│   │   ├── working.py       ← session state
│   │   └── summarizer.py    ← compresses persistent memory for prompt inclusion
│   │
│   ├── agent/
│   │   ├── loop.py          ← the agent loop (hand-written, no framework)
│   │   ├── prompts.py       ← system prompt, tool descriptions
│   │   └── mcp_client.py    ← connects to the MCP server
│   │
│   ├── mcp_server/
│   │   ├── server.py        ← MCP server entry point
│   │   ├── tools/           ← one file per tool
│   │   └── schemas.py       ← pydantic models for tool inputs/outputs
│   │
│   ├── llm/
│   │   ├── client.py        ← anthropic client wrapper with caching config
│   │   └── extraction.py    ← Haiku-based extraction helper
│   │
│   ├── api/
│   │   ├── main.py          ← FastAPI app
│   │   └── routes/          ← chat, jobs, applications, profile endpoints
│   │
│   └── config.py            ← settings, paths, model choices
│
├── evals/
│   ├── test_set.yaml
│   ├── run_evals.py
│   ├── metrics.py
│   └── reports/             ← output of eval runs, tracked over time
│
├── data/
│   ├── raw/                 ← fetched job postings (jsonl per source per day)
│   ├── chroma/              ← ChromaDB persistent files
│   ├── jobs.db              ← SQLite
│   └── user/                ← resume, profile, preferences (gitignored)
│
├── frontend/                ← React + TypeScript + Vite (Phase 4)
│
└── scripts/
    ├── run_ingestion.py
    ├── run_agent_cli.py     ← chat with the agent from the terminal
    └── inspect_db.py
```

---

## 6. Phased Implementation Plan

Each phase ends with something demonstrable and evaluated.

### Phase 0 — Foundations (Day 1)
- Repo setup, pyproject.toml, .env, config
- SQLite schema for jobs, applications, preferences
- ChromaDB initialization
- Basic Anthropic + sentence-transformers wiring, verified with a hello-world call

**Definition of done:** can insert a fake job into SQLite, embed a string into ChromaDB, and call Sonnet with a test prompt. All from CLI.

### Phase 1 — Ingestion Pipeline (Days 2–4)
- One fetcher (RemoteOK — has clean JSON API, best to start)
- Normalizer + deduper
- Chunker
- Extractor (Haiku-powered, with pydantic schema)
- Pipeline orchestrator
- Persist to both stores
- Ingest ~500 real jobs

**Definition of done:** `python scripts/run_ingestion.py` populates both stores with real job data. Inspect via `scripts/inspect_db.py`.

### Phase 2 — MCP Server + First Two Tools (Days 5–6)
- MCP server skeleton
- `search_jobs` and `semantic_job_search` tools implemented
- Verify from Claude Desktop (manual sanity check)

**Definition of done:** in Claude Desktop, can ask "find Python backend roles" and see the tool called with correct filters, results returned.

### Phase 3 — Agent Loop + Memory (Days 7–10)
- Hand-written agent loop that connects to MCP server
- Persistent memory: profile ingestion (parse a PDF resume), preferences CRUD
- Working memory: session state
- Persistent memory summarization for prompt inclusion
- CLI chat interface

**Definition of done:** `python scripts/run_agent_cli.py` lets me have a multi-turn conversation. Agent uses tools correctly, remembers within a session, has my profile in context.

### Phase 4 — Remaining Tools + Feedback Signals (Days 11–13)
- `analyze_fit`, `draft_cover_letter`, `find_skill_gaps`, `track_application`, `update_preferences`, `get_application_status`
- Feedback signal capture (viewed/saved/rejected)
- Learned_facts extraction (agent updates durable inferences after N signals)

**Definition of done:** can complete a full workflow: search → analyze fit on a specific job → draft cover letter → track application. All from CLI.

### Phase 5 — Evaluation Harness (Days 14–15)
- Test set of ~50 queries
- Eval runner
- All metrics implemented
- First eval report generated

**Definition of done:** `python evals/run_evals.py` produces a scored report. Regressions caught automatically.

### Phase 6 — Second and Third Ingestion Sources (Day 16)
- WeWorkRemotely (RSS parser)
- HN "Who's Hiring" (monthly thread parser)
- Deduper handles cross-source dupes

**Definition of done:** ingestion runs against all three sources, dedupes correctly.

### Phase 7 — FastAPI + React Frontend (Days 17–22)
- FastAPI routes wrapping the agent
- Chat UI with streaming
- Application tracker (kanban)
- Profile editor
- Job feed with filter sidebar (traditional UI as fallback)

**Definition of done:** everything works from browser, not just CLI.

### Phase 8 — LangGraph Migration Evaluation (Day 23)
- Prototype the agent loop in LangGraph
- Compare: code complexity, debuggability, feature velocity
- Decide: migrate or stay hand-written. Document reasoning in decisions log.

### Phase 9 — Polish, Docs, Public Write-up (Days 24–25)
- README with setup + demo GIFs
- Architecture doc for public consumption
- Blog post: "Building a Personal Job Search Agent — Lessons in Agentic AI"
- Deploy an anonymized demo if possible

**Total: ~4 weeks of focused work.**

---

## 7. Risks and Open Questions

**Risks:**
- RemoteOK / WWR / HN data volume may be lower than expected — mitigate by adding more sources
- Structured extraction quality on messy postings — mitigate with schema iteration + eval-driven tuning
- MCP + Claude Sonnet cost may exceed $2/day target — mitigate with caching and Haiku-first routing where possible
- Frontend phase may slip — acceptable; CLI is a valid demo

**Open questions to resolve during build:**
- Exact chunking strategy for job postings — test 200/500/1000 token chunks in Phase 1
- Whether to add a re-ranker on top of ChromaDB — defer to Phase 5 based on eval scores
- Whether to add a lightweight vector cache for repeated queries — defer to Phase 7 based on latency data
- How aggressive to be with learned_facts — start conservative (require 5+ signals), tune with eval

---

## 8. Success Criteria

**Portfolio success:**
- End-to-end demo runs cleanly
- Eval report shows measurable, defensible numbers on all 7 metrics
- Every JD skill area has a specific artifact I can point to
- Code is clean enough to open in an interview and walk through

**Personal-use success:**
- I actually use it during my job search
- It surfaces at least one role I would have missed otherwise
- It saves me time on cover letters and fit analysis
- I collect real feedback data that informs iteration

---

## 9. Decisions Log

*(To be updated as the project evolves. Every non-obvious change should be logged here with reasoning.)*

| Date | Decision | Reasoning |
|---|---|---|
| Day 0 | SQLite + ChromaDB (not Postgres) | Local, free, portable. Migrate later if needed. |
| Day 0 | Hand-written agent loop, not LangChain | Learning goal: understand every token. Reevaluate LangGraph in Phase 8. |
| Day 0 | Haiku for extraction, Sonnet for agent | Cost/capability match per task. |
| Day 0 | Local embeddings (MiniLM), not API | Zero marginal cost, good enough for job descriptions. |
| Day 0 | RemoteOK first, WWR + HN later | Cleanest API of the three; get pipeline working before adding parsing complexity. |
