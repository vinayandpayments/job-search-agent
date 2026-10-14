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

**Primary success criterion (v2):** the learning. This project is the vehicle for understanding production agentic AI at the deepest level — RAG internals, tool calling, memory, context/harness engineering, multi-agent orchestration, and predictive evaluation. A shipped feature whose design I can't defend from first principles is a failure even if it works. Interface is **CLI only** — the React frontend is out of scope (dropped from the roadmap).

### Working Agreement (how this gets built)

Discussion is the primary mode; implementation is the residue of decisions.

1. Every module opens with a **concept walkthrough** — internals, not summaries — then a **decision menu**: each real option with honest tradeoffs and a recommendation.
2. **Vinay makes the call.** Non-trivial forks are not implemented undecided; silence means ask, not default.
3. **Cross-examination runs both ways.** Vinay challenges claims; Claude asks check-questions back. Being corrected is the process working.
4. Code lands in **small, explainable increments** — nothing ships that Vinay couldn't re-derive.
5. Every decided fork gets a Decisions Log row (§9) including the **rejected alternatives and why** — interview-ready reasoning is a deliverable.

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
| **Harness Engineering** | Everything around the model that makes it reliable, built by hand: the agent loop itself, context assembly + token budgeting, tool-result truncation, retry/failure policy, per-turn tracing/observability. M5 is dedicated to this; M8 extends it to multi-agent orchestration. |

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

> **Provider note (Day 0):** The primary LLM is **Google Gemini**, not Anthropic Claude — the builder has a Gemini API key, not an Anthropic one. A "Flash" tier covers cheap high-volume tasks; a "Pro" tier covers reasoning-heavy, user-facing tasks. A Grok (xAI) key exists and is deferred as a future fallback. See §9 Decisions Log.
>
> **Concrete model IDs live in `src/config.py` (single source of truth), not here** — they churn fast. As of Day 0 the working key is **free-tier and billing is intentionally OFF**. Free tier (a) can no longer call `gemini-2.5-*` ("no longer available to new users") and (b) has **no usable Pro quota** (Pro models return 429 `free_tier_input_tokens` exhausted). Decision: run Flash across the board — `gemini-3.5-flash-lite` for cheap tasks, `gemini-3.6-flash` for the agent tier — and do **not** pay for Pro. If Flash quality proves insufficient for the agent tier, the fallback is a **free/open-source model** (e.g. a local model via Ollama), not billed Gemini Pro.

| Task | Tier | Reason |
|---|---|---|
| Structured extraction during ingestion | Gemini Flash (lite) | Cheap, fast, schema-constrained JSON via `response_schema`; runs on every chunk |
| Embedding generation | `sentence-transformers/all-MiniLM-L6-v2` (local) | Free, fast, good enough for job descriptions; no API cost per embedding |
| Agent loop (tool calling + reasoning) | Gemini Flash (`gemini-3.6-flash`) | Needs to reason about which tool to call, handle multi-step plans, refuse fabrication. Would prefer Pro, but free tier forbids it; open-source fallback if quality lags. |
| Cover letter drafting | Gemini Flash (`gemini-3.6-flash`) | Quality of output matters, this is user-facing content |
| Fit analysis (resume vs job) | Gemini Flash (`gemini-3.6-flash`) | Nuanced comparison |
| Session summarization (compressing old turns) | Gemini Flash (lite) | Simple task, runs frequently |

**Cost envelope target:** under $2/day of personal use assuming ~50 messages/day.

**Caching strategy:** system prompt + tool definitions + user profile summary form a stable prefix on every agent call → these should be cached. **Note:** Gemini's context caching differs from Anthropic's automatic prefix caching — it uses explicit `CachedContent` objects with a minimum-token threshold, plus implicit caching on some models. The stable prefix doesn't exist until the agent loop is built, so the concrete caching mechanism is **deferred to Phase 3** when the prefix is real. Goal remains: only conversation tail + tool results vary.

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

**LLM SDK:** official `google-genai` Python SDK (the new unified Google GenAI SDK, `from google import genai`). Direct API calls, no wrapper. Grok (xAI) is deferred as a future fallback provider.

**Vector store:** ChromaDB (already familiar to me, local, free).

**Embeddings:** `sentence-transformers/all-MiniLM-L6-v2` locally (no API cost).

**Backend framework:** FastAPI (async, clean) — only if an HTTP API is ever needed; the primary interface is the CLI.

**Frontend:** none — dropped from scope (see §9 Day 1). The CLI is the interface; agent quality is the demo.

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
└── scripts/
    ├── run_ingestion.py
    ├── run_agent_cli.py     ← chat with the agent from the terminal
    └── inspect_db.py
```

---

## 6. Learning-Module Roadmap (v2)

> **Restructured (Day 1 of module work):** the original phase plan (Phases 0–9) is replaced by learning modules. Mapping: Phase 0 → done; Phase 1 → done (M1 retro-opens its quality decisions); Phase 2 → M4; Phase 3 → M5+M6; Phase 4 → folded into M5/M7; Phase 5 → M7 (but evals now start in M1); Phase 6 → deferred, slot after M7; Phase 7 (frontend) → **dropped, CLI only**; Phase 8 (LangGraph) → replaced by M8 (hand-built multi-agent); Phase 9 → M10.

Each module carries: **Learning goals · Discussion questions (answered with Vinay BEFORE code) · Build · Eval artifact · Definition of done.** Modules end with something demonstrable *and* a metric.

### M1 — Grounding Starts at Ingestion *(retro; in progress)*
- **Learning goals:** data quality as the root of no-hallucination; designing validity predicates; when an extractor must say null.
- **Discussion:** what predicate makes a record "a job"? Where does the quality filter live (normalizer vs separate stage)? Should extraction require a quoted evidence span? What are the first eval assertions?
- **Build:** junk filter, full HTML unescaping, grounded extraction prompt; `evals/` gets its first data-quality assertions (not waiting for M7).
- **Eval artifact:** % non-jobs in store (target ~0); % extracted fields traceable to source text.
- **DoD:** re-ingestion produces a store where every row passes the validity assertions; known junk examples are rejected with logged reasons.

### M2 — Storage Internals *(retro discussion)*
- **Learning goals:** vector DB landscape (Chroma vs pgvector/Qdrant/FAISS); how HNSW search actually works; embedding anatomy (MiniLM pooling, 384 dims, cosine vs L2); where metadata filtering breaks down.
- **Discussion:** would we still choose SQLite+Chroma knowing the internals? What would force a migration?
- **Build:** small experiments (recall vs ef_search, distance-metric comparison); code changes only if we decide differently.
- **Eval artifact:** measured recall/latency table from our own data.
- **DoD:** decision log row: storage choice re-affirmed or changed, with evidence.

### M3 — Chunking Lab *(deep dive)*
- **Learning goals:** chunking strategies (fixed / recursive / semantic / section-aware) and how chunk geometry drives retrieval quality.
- **Discussion:** what does a "good chunk" mean for job postings? What golden queries define success?
- **Build:** golden retrieval set (~20 query→expected-job pairs from ingested data); harness comparing strategies on precision@k / MRR.
- **Eval artifact:** per-strategy scoreboard; chosen strategy justified by numbers.
- **DoD:** chunker configured by evidence, not defaults; scoreboard committed under `evals/reports/`.

### M4 — Tool Calling & MCP
- **Learning goals:** tool-description engineering; the `search_jobs` vs `semantic_job_search` selection tension; debugging wrong-tool calls.
- **Discussion:** tool schema design; how descriptions steer selection; what a tool-selection eval looks like.
- **Build:** MCP server + first two tools; tool-selection eval queries.
- **Eval artifact:** tool-selection accuracy on ~15 annotated queries.
- **DoD:** from an MCP client, filter-y queries hit `search_jobs`, fuzzy ones hit `semantic_job_search`, measured.

### M5 — The Agent Loop = Harness Engineering
- **Learning goals:** what a harness is: the loop, context assembly, token budgeting, tool-result truncation, retries, tracing; context engineering per turn; citations + refusal ("not found in source") wired into the loop, not hoped for.
- **Discussion:** context budget layout; truncation policy; failure/retry policy; trace format.
- **Build:** hand-written loop (`src/agent/loop.py`), CLI chat, per-turn trace log.
- **Eval artifact:** citation completeness; fabrication-refusal rate on synthetic no-answer queries.
- **DoD:** multi-turn CLI conversation with visible traces; refusal cases pass.

### M6 — Memory Engineering
- **Learning goals:** persistent / working / summarized tiers; summarize-before-inject discipline; how Claude-Code-style memory works (files + index as live example).
- **Discussion:** what belongs in each tier; when summaries regenerate; memory poisoning risks.
- **Build:** `src/memory/*` (profile ingestion, preferences CRUD, session state, summarizer).
- **Eval artifact:** memory evals — recall across sessions, adaptation after feedback signals.
- **DoD:** agent demonstrably uses profile + past signals; summaries stay under a token budget.

### M7 — Evaluation Harness (consolidated)
- **Learning goals:** metrics that *predict* performance vs vanity metrics; regression discipline.
- **Discussion:** which of the 7 metrics (tool accuracy, precision@k, citations, refusal, preference-learning, cost, latency) predict real-use success, and how we'd know.
- **Build:** ~50-query test set + `evals/run_evals.py` + report with regressions (absorbs M1–M6 artifacts).
- **DoD:** one command produces a scored report; a deliberate regression is caught.

### M8 — Multi-Agent Orchestration *(from scratch; replaces LangGraph phase)*
- **Learning goals:** orchestrator/worker patterns; parallel sub-agents with different missions; central synthesis; per-agent observability.
- **Discussion:** when multi-agent beats single-agent (and when it's just overhead); shared-state vs message-passing; failure isolation.
- **Build:** orchestrator spawning parallel sub-agents (e.g. fit-analysis fan-out across job clusters), synthesis step, CLI trace viewer.
- **Eval artifact:** quality + latency vs single-agent baseline on the same tasks.
- **DoD:** one query fans out to N agents and returns a synthesized, traceable answer.

### M9 — Caching & Inference Economics
- **Learning goals:** Gemini CachedContent vs implicit caching vs Anthropic-style prefix caching; embedding caches; measuring $/query.
- **Build:** cache the stable prefix (deferred from Phase 0); embedding cache; cost table.
- **DoD:** measured cost/latency before vs after caching.

### M10 — Write-up & Polish
- README, architecture doc, demo (CLI recording), blog post. No frontend.

### Later / optional
- Additional sources (WWR RSS, HN Who's Hiring) — slot after M7, exercises the messy-text extraction path.

---

## 7. Risks and Open Questions

**Risks:**
- RemoteOK / WWR / HN data volume may be lower than expected — mitigate by adding more sources
- Structured extraction quality on messy postings — mitigate with schema iteration + eval-driven tuning
- MCP + Claude Sonnet cost may exceed $2/day target — mitigate with caching and Haiku-first routing where possible
- Discussion-first pace is slower than build-first — accepted deliberately; understanding is the deliverable

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
| Day 0 | **Primary LLM = Gemini, not Anthropic Claude** | No Anthropic API key available; builder has Gemini + Grok keys. Gemini 2.5 Flash for cheap high-volume tasks (extraction, summarization), Gemini 2.5 Pro for reasoning/user-facing tasks (agent loop, cover letters, fit). Uses the `google-genai` SDK. Grok deferred as fallback. Supersedes the "Haiku/Sonnet" rows above and the "Anthropic SDK" note in §4.6. |
| Day 0 | Gemini prompt caching deferred to Phase 3 | Gemini's caching model (explicit `CachedContent` + implicit) differs from Anthropic's automatic prefix caching; the stable prefix doesn't exist until the agent loop is built. |
| Day 0 | **Flash-only, no billing; open-source fallback if needed** | The free-tier key can't call `gemini-2.5-*` and has no Pro quota (429). Verified working: `gemini-3.5-flash-lite`, `gemini-3.6-flash`. Billing is intentionally OFF — agent-tier tasks run on Flash; if quality lags, fall back to a free/open-source model (e.g. Ollama-hosted), not paid Pro. Concrete IDs pinned in `src/config.py`. |
| Day 1 | **Roadmap restructured into learning modules (§6 v2)** | Primary aim clarified: deep learning of agentic AI, not shipping speed. Phases → modules M1–M10, each opening with discussion before code. Rejected: keeping the phase plan as-is (it front-loaded building over understanding). |
| Day 1 | Keep Phase 0/1 code; retro-open its decisions | Rebuilding scaffolding teaches little; the decisions are where learning lives. Storage choice, chunking, and extraction quality get re-examined as modules (M1–M3) and changed if discussion concludes differently. Rejected: full restart (2 sessions of re-plumbing for no new insight). |
| Day 1 | RAG stays job-specific for now | Depth over abstraction: learn internals in context first; genericizing into a reusable engine is mechanical later. Rejected (for now): a generic `src/rag/` package or standalone pip package. |
| Day 1 | Multi-agent after single-agent loop works (M8) | Must deeply understand one hand-written loop before orchestrating several; M8 replaces the LangGraph-migration phase — orchestration will also be hand-built. Rejected: designing multi-agent-first (carries complexity before understanding). |
| Day 1 | **Frontend dropped — CLI only** | Learning goals live in the agent/RAG/eval layers; a React UI adds surface area with no agentic learning. `frontend/` removed from repo tree. |
