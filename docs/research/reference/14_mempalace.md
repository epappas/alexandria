# Reference: MemPalace — sibling project, influential on three specific points

**Source:** `raw/36_mempalace.md` (comprehensive verbatim preservation of README / MISSION / CLAUDE.md / the-palace / memory-stack / knowledge-graph / contradiction-detection / agents / aaak-dialect / hooks / mining / mcp-tools)

**Repo:** https://github.com/mempalace/mempalace, MIT, v3.3.0 at fetch (v4.0.0-alpha in the near ROADMAP), creators Milla Jovovich + @bensig. Official site `mempalaceofficial.com` (the repo calls out impostor domains in a scam warning).

## Why this doc exists

MemPalace is a local-first Python personal-memory system with an MCP surface. It is a **sibling**, not a competitor. We share many values — local-first, zero API mandatory, MCP-first, Zettelkasten-inspired, pluggable backend — but we make different bets on the load-bearing retrieval question. Reading mempalace in depth sharpened three ideas for alexandria and clarified three places where we deliberately diverge. This doc records both.

## Where we agree

1. **Local-first, privacy by architecture.** Every byte stays on the user's machine unless they opt in. Encrypted credentials via OS keyring. No telemetry, no phone-home.
2. **MCP-first integration.** The system is a knowledge/memory engine exposed through MCP tools to whatever agent the user runs — Claude Code, Codex, OpenClaw, Cursor, Claude Desktop. Both projects explicitly refuse to be chat clients themselves.
3. **Zettelkasten lineage.** Both cite Luhmann's Zettelkasten and apply the *"small cross-referenced index cards that point to each other"* pattern, though with different metaphors — MemPalace uses the method-of-loci palace structure (wings → rooms → drawers), alexandria uses Karpathy's three-layer (raw → compiled wiki → schema).
4. **Organization by people/projects/topics.** MemPalace's wing-per-person-or-project, room-per-topic maps almost exactly onto alexandria's workspace-per-project, topic-subdirectory-per-topic. Same idea, different names.
5. **Pluggable storage backend.** MemPalace has `backends/base.py` (ChromaDB default, PostgreSQL / LanceDB / PalaceStore planned in v4). alexandria has its SQLite+filesystem split with the same spirit of swappability for the index layer.
6. **Append-only, incremental.** Both reject destructive rebuilds. Both treat a crash as "leave existing data untouched."
7. **Background everything.** MemPalace's hooks move filing work off the chat window entirely. alexandria's daemon moves scheduled synthesis, source polling, and event ingestion to the background. Neither tool wants to consume user chat tokens for bookkeeping.

## Where we deliberately diverge

### 1. Storage unit: verbatim chunks vs compiled wiki pages

MemPalace's foundational promise is *"Verbatim always — Never summarize, paraphrase, or lossy-compress user data."* Every word the user has said is a drawer of ~800 characters, stored and searchable exactly as it was spoken. The metric is 100% recall.

alexandria takes a different position. The **raw layer** is verbatim (immutable source material), but the **wiki layer** is explicitly synthesized — concept pages, entity pages, cross-references, distilled summaries with cited footnotes. Karpathy's own framing is *"the LLM incrementally 'compiles' a wiki"*, and the compilation step is load-bearing. Our metric is not recall — it is **compounding knowledge**: the user's understanding of a topic should deepen over time as more sources are compiled into the same page.

These are different products targeting different failure modes:

- **MemPalace's failure mode**: "I can't remember what we said three months ago about X." The fix is verbatim storage with high-recall retrieval.
- **alexandria's failure mode**: "I've read 50 papers about X and I still don't have a coherent understanding of X." The fix is compilation into durable pages.

**Neither is wrong.** A sophisticated user could run both: mempalace capturing every conversation verbatim for "what exactly did we say?" recall, alexandria compiling the important material into a durable wiki for "what do we understand about this?" synthesis. They would not compete for the same slot on the user's disk.

### 2. Retrieval model: vector search vs agentic navigation

**Both targets named explicitly:**

- **MemPalace targets** multi-modal, fuzzy-recall personal AI memory at conversational latencies — *"remember when we talked about that idea but in vague terms"* (MISSION.md). Their query shape is *"recall something semantically similar to this hint"* over a corpus of verbatim conversation chunks. **Vector search wins this query shape.** Embeddings are exactly the right primitive for fuzzy semantic recall over chunked text, and 96.6% R@5 on LongMemEval is the right number to publish.
- **alexandria targets** single-user, retroactive, exact-identifier-heavy queries over compiled wiki pages with cited provenance — *"what did I decide about the auth refactor in March, and what's the source"* (`research/reference/01_karpathy_pattern.md` + invariant #15). Our query shape is *"navigate from a known concept or identifier through cross-references to verbatim source quotes"*. **Agentic navigation wins this query shape** because the agent reads pages it chose, follows footnotes via deterministic hash anchors (`13_hostile_verifier.md`), and walks the belief supersession chain (`19_belief_revision.md`).

These are different products at different points on the design space. Neither is wrong for its target. A user who needs both could run both side-by-side without conflict.

MemPalace uses ChromaDB vector embeddings with BM25 hybrid fallback and publishes serious benchmark numbers: 96.6% R@5 raw on LongMemEval, 98.4% hybrid, ≥99% with LLM rerank. These are real numbers on a real benchmark **for the LongMemEval query shape** (fuzzy semantic recall over conversation chunks). They do not transfer to alexandria's query shape, and neither system's target invalidates the other.

alexandria's `01_vision_and_principles.md` invariant #13 explicitly rejects vector stores. We built the case in `research/reference/12_agentic_retrieval.md` and `13_agentic_retrieval_design_space.md` around Anthropic's own published guidance (*"our architecture uses a multi-step search that dynamically finds relevant information, adapts to new findings, and analyzes results"*) and the CatRAG "static graph fallacy" critique. We expose navigation primitives (`list`, `grep`, `search` via FTS5, `read`, `follow`, `events`, `timeline`, `history`) and let the agent compose them. The agent IS the retriever.

The divergence is principled. Vector search vs agentic navigation is a **design choice**, not a correctness question:

- **Vector search wins** when the unit is a small chunk and the query is "find the most similar chunk to this question" — MemPalace's exact benchmark shape. Fair and impressive.
- **Agentic navigation wins** when the unit is a whole page with cited footnotes and the query is "what do I already understand about this, and which raw sources back it up" — our shape. The agent composes multiple reads, follows citations, walks the log, and synthesizes. No benchmark exists that matches this exact workflow because the answer's quality depends on the agent behind the tools, not the tools alone.

We explicitly do not adopt vectors because doing so would contradict an invariant we already locked in. MemPalace's 96.6% is not a reason to change our mind — it is a reason to respect the other bet as valid and move on.

### 3. Knowledge graph: temporal ER triples vs provenance + events + wiki pages

MemPalace has a first-class temporal ER knowledge graph with `subject → predicate → object [valid_from → valid_to]` triples in SQLite — like Zep's Graphiti, local and free. It supports `kg_query`, `kg_add`, `kg_invalidate`, `kg_timeline`, `kg_stats` as MCP tools.

alexandria has the same information distributed across:

- **`documents.superseded_by`** — supersession chain.
- **`wiki_claim_provenance`** — each footnote in a wiki page linked to the raw source it cites.
- **`wiki_log_entries`** — ingest/query/lint events with touched document lists and timestamps.
- **`events` table** — fine-grained project activity (GitHub, calendar, Slack, etc.) with `occurred_at` and a `refs` JSON field for cross-stream identifiers.

The agent composes these via MCP tools rather than querying a single pre-built graph. This is the CatRAG position from `13_agentic_retrieval_design_space.md`: static graphs have the *static graph fallacy* (fixed transition probabilities, hub-node semantic drift); agentic navigation avoids the problem by construction because the agent adapts to the query.

One honest concession: the explicit `valid_from / valid_to` shape in mempalace is cleaner for *"what was true in January?"* queries than our event-table + supersession approach. We could adopt the temporal predicate idea as a lint-time extraction without building a retrieval pipeline on top of it — see "What we will revisit later" below.

## What mempalace teaches us (three adoptions)

### ADOPTION 1 — The L0/L1 wake-up stack with bounded token budgets

MemPalace's `layers.py` formalizes what alexandria's `guide()` tool already does informally:

- **L0 (~50-100 tok)** — identity. Plain text file `~/.mempalace/identity.txt`. "Who is this AI, who does it work for, what's the project."
- **L1 (~500-800 tok)** — essential story. Auto-generated from the top-importance drawers, grouped by room, truncated to 3200 chars / 15 drawers / 2000-row scan cap.
- **L2** — on-demand retrieval, wing/room filtered. Fires when a topic comes up.
- **L3** — deep semantic search. Fires when explicitly asked.

Wake-up total ~600-900 tokens, leaving ~95% of the context window free for the actual work.

**This is directly applicable to alexandria.** Our `guide(workspace)` currently loads SKILL.md + overview.md + index.md + log.md tail + self-awareness block in an ad-hoc way. Formalizing it as:

- **L0** — workspace identity: `workspaces/<slug>/identity.md` if present (or auto-generated from workspace config), plus SKILL.md core rules. Hard budget: 500 tokens.
- **L1** — essential state: overview.md + index.md top sections + last 10 log entries + pending counts (sources, subscriptions, events). Hard budget: 1500 tokens.
- **L2** — on-demand reads via existing `list`/`read`/`search`/`grep` primitives. No change; they already fire on demand.
- **L3** — deep composition via multiple primitives + subagents. Same agentic navigation we already have.

Benefits:
- **Predictable token cost per session.** The user can budget.
- **Smaller cold-start context** — more of the window is free for the actual task.
- **Explicit tiering that the agent can reason about** — *"I should have read the overview (L0+L1) before going to L3."*
- **Prompt caching friendly** — L0 + L1 are stable and cacheable per the Anthropic caching rules in `raw/35_*`. L2/L3 are dynamic. The breakpoint naturally lands after L1, and we already structure calls that way.

This is pure architectural discipline with no downside. Adopting.

### ADOPTION 2 — Conversation transcript ingestion as a source type

MemPalace's `convo_miner.py` ingests conversation history from five formats:
- Claude Code JSONL transcripts (`~/.claude/projects/*/*.jsonl`)
- ChatGPT exports
- Slack exports
- Markdown conversation files
- Plain text transcripts

And exchange-pair chunking (`>` quoted user turn + AI response = one unit), with a fallback to paragraph chunking. Mega-file splitting for concatenated multi-session exports.

**alexandria has no such source today and it is the biggest gap in the knowledge-engine story.** The user spends hours in Claude Code thinking with their AI. When the session ends, that context evaporates. alexandria's promise of retroactive query (`01_vision_and_principles.md` #15) is hollow if "the conversation where I figured out the auth architecture" is not part of the knowledge engine.

The right implementation:

- **New adapter: `conversations`** (a hybrid SOURCE + EVENT_STREAM). Input: a directory of transcript files. Output: one markdown document per session in `raw/conversations/<client>/<yyyy-mm-dd>-<session-id>.md`, plus structured events in the `events` table (session_started, user_turn, assistant_turn, tool_call, session_ended) tagged with client name.
- **Five format detectors** at minimum: `claude-code` (`~/.claude/projects/*/*.jsonl` format — roles `user` / `assistant`, tool_use / tool_result blocks), `chatgpt` (OpenAI export JSON), `cursor` (their local session format), `codex` (their session format), `markdown` (quoted-turn style).
- **Normalization** into the shared markdown schema with citations to the client's session file so provenance is preserved.
- **Incremental mine** via SHA-256 content hash (same mechanism atomicmemory's compiler and our source adapters already use).

Full design lives in the new `architecture/12_conversation_capture.md` doc.

### ADOPTION 3 — Auto-save hooks for the capture-as-you-go loop

MemPalace's two hooks on Claude Code Stop + PreCompact events:

- **Stop hook** fires every N human messages (default 15), blocks the AI, and in silent mode kicks off `mempalace mine` on the transcript directory in the background. Uses `stop_hook_active` to prevent infinite loops.
- **PreCompact hook** always fires before context compaction — emergency save.

Zero extra tokens (bash scripts, local filesystem only). The AI does the classification because it has the context; the hook just triggers the timing.

**alexandria needs the same.** The shape is:

- **`alexandria hooks install claude-code`** — writes the right block to `.claude/settings.local.json` with a hook script `~/.alexandria/hooks/stop.sh` and `~/.alexandria/hooks/precompact.sh`.
- **Stop hook (`stop.sh`)** — counts turns; every N messages triggers `alexandria mine conversations --workspace <default>` as a detached background process. Honors `stop_hook_active` to avoid loops. Silent by default; `ALEXANDRIA_VERBOSE=1` enables a blocking mode that tells the agent to synthesize before stopping.
- **PreCompact hook (`precompact.sh`)** — always fires, runs the same mine in the background.
- **Cursor / Codex / Windsurf equivalents** — each client has its own hook shape but the capture target is identical. Install subcommands write the right config for each.
- **`alexandria hooks uninstall`** — removes the entries cleanly.

The hook scripts themselves are tiny — under 100 lines of bash each. The code that matters is the `alexandria mine conversations` command, which is the Adoption 2 adapter's primary entry point.

**The combined effect** of Adoption 2 + Adoption 3 is the closed loop the user asked for: a knowledge engine that continuously accumulates the user's own thinking-with-AI sessions without any manual curation step. Every Claude Code conversation becomes raw material. Every weekly scheduled synthesis (from `10_event_streams.md`) can then compile the recent conversations into wiki updates. The user's thinking compounds, automatically, in the background.

## What we will revisit later (not MVP adoptions)

### Temporal validity predicates as a lint extraction

MemPalace's `subject → predicate → object [valid_from → valid_to]` shape is strictly cleaner for temporal queries than our current setup. We could add a **lint-time extractor** that reads wiki pages and extracts `(subject, predicate, object, valid_from?, valid_to?, source_page)` tuples into a `wiki_facts` side table. The agent queries this via a new `facts(subject?, predicate?, as_of?)` tool when it needs temporal scoping.

This is **complementary to**, not a replacement for, agentic navigation. The agent still reads pages for the full story; the `facts` table is a fast index for "what was true in January." It respects the agent-as-retriever principle because the agent decides when to consult it.

Filed as an open question in `07_open_questions.md` — not MVP, worth doing if retroactive temporal queries feel slow in practice.

### Contradiction-detection categories

MemPalace names three concrete categories:
- **Attribution conflicts** — wrong actor credited for an action.
- **Temporal errors** — wrong dates, tenures, durations.
- **Staleness** — facts superseded by newer sources.

Our `04_guardian_agent.md` lint pass currently lists "factual contradictions across articles" as a single heuristic bullet. Sharpening into these three explicit categories gives the agent better-scoped reports. Since MemPalace flags their own contradiction-detection as "experimental / planned," we are not copying a shipped feature — we are copying a *taxonomy* that is useful for structuring our existing lint output.

Worth doing as a small update to `04_guardian_agent.md`'s lint section. Filing as a minor update, not a new doc.

### Per-agent diary metadata

MemPalace has `wing_reviewer`, `wing_architect`, `wing_ops` — separate wings for different named agents. In alexandria terms, this is "per-agent metadata on wiki writes" — when Claude Code writes a page, record `client=claude-code`; when Cursor writes, record `client=cursor`. Useful for `history(workspace, client="cursor")` queries or for lint rules like "Claude Code wrote 40 pages this month but Cursor wrote 0 — is Cursor actually being used?"

Small schema addition to `wiki_log_entries`, not a new architecture concept. Filed as a minor update.

## The summary for future readers

alexandria and mempalace are two locally-hosted, MCP-first, Zettelkasten-inspired personal knowledge systems with different retrieval bets. They complement rather than compete. From mempalace we adopt three things cleanly and defer three more:

**Adopted immediately:**
1. Formalize `guide()` as an L0/L1 tiered wake-up with bounded token budgets.
2. Add conversation-transcript ingestion as a new source adapter covering Claude Code, Cursor, Codex, ChatGPT, Slack, and markdown formats (new doc `12_conversation_capture.md`).
3. Add Stop + PreCompact hooks for Claude Code / Cursor / Codex / Windsurf that trigger `alexandria mine conversations` in the background.

**Deferred / minor updates:**
4. A `wiki_facts` side table for temporal predicate queries (open question, revisit if temporal queries feel slow).
5. Explicit contradiction-detection taxonomy (attribution / temporal / staleness) as a lint update.
6. Per-client metadata on wiki writes.

**Explicitly not adopted:**
- Vector embeddings as the retrieval layer (contradicts invariant #13).
- Verbatim-chunk storage as the primary unit (conflicts with the compiled wiki model).
- A first-class knowledge graph with PPR-style retrieval (CatRAG critique still applies).
- AAAK compression (their own benchmarks show a regression from verbatim).

The next reader of this doc should be able to tell, from this list alone, where alexandria is taking influence from mempalace and where the influence stops — and why.
