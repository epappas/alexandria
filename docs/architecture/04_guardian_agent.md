# 04 — Guardian Agent

> **Cites:** `research/reference/01_karpathy_pattern.md`, `research/reference/02_lucasastorian_impl.md`, `research/reference/03_astrohan_skill.md`

The guardian is the only component that writes to a workspace's wiki. It is an LLM agent — running inside Claude.ai, Cursor, or `alexandria chat` — that connects to the local MCP server and operates on one workspace.

## What the agent knows on session start — the tiered wake-up

Heavily influenced by mempalace's `MemoryStack` (`research/reference/14_mempalace.md`). The `guide()` call returns two explicitly-tiered layers with hard **output** token budgets. L2 and L3 happen on-demand via the existing navigation primitives and are not pre-loaded. The budgets below are `max_output_tokens` for the `guide` tool's response — they are not bounds on the surrounding `tools` + `system` prefix that the caller (Claude Code, etc.) sends, which is sized by the MCP tool schema layer and naturally clears Anthropic's prompt-caching minimums (4096 tokens for Opus 4.6, 2048 for Sonnet 4.6 — see `research/raw/35_anthropic_prompt_caching.md`).

### L0 — Identity (≤ 500 output tokens, always returned)

Stable across sessions for the same workspace. Cacheable when the caller treats `guide()` output as a system-prompt prefix.

Contents:
1. **The contract** — "You are connected to LLM Wiki workspace `<name>`. You maintain raw/ and wiki/. The user reads; you write. The user curates; you cross-link. Every factual claim on a wiki page must cite a source via footnote with a verbatim quote anchor (see `13_hostile_verifier.md`)."
2. **The workspace identity** — name, description, scope, topics, dates-of-relevance, creator. Read from `workspaces/<slug>/identity.md` if present; else auto-generated from `workspaces/<slug>/config.toml`.
3. **The core schema rules** — the short distilled version of SKILL.md. Long-form SKILL.md is available via `read` if the agent needs it; the L0 block is the must-know distillation.

### L1 — Essential state (≤ 1500 output tokens, dynamic)

Generated fresh on every `guide()` call. Reflects current workspace state.

Contents:
1. **Wiki counts** — total pages, pages per topic, raw source count per adapter.
2. **`wiki/overview.md` body** — the mandatory hub page (capped at 600 output tokens).
3. **`wiki/index.md` top sections** — the topic-level table of contents.
4. **Last 15 log entries** — parsed from `wiki_log_entries` for fast structured display: ingest / query / lint / synthesis events with dates, op, run_id, touched-pages list.
5. **Pending queues** — counts and adapter names for pending `subscriptions_queue` items, event-stream items not yet synthesized, and synthesis runs awaiting review.
6. **Self-awareness summary** — what the agent wrote in the last 7 days, which pages it touched, which runs are still in `pending` or `verifying` state.
7. **Eval health summary** — current M1-M5 scores from `14_evaluation_scaffold.md` with healthy/degraded/broken status.

### Combined wake-up: ≤ 2000 output tokens

L0 + L1 together return ≤ 2000 output tokens for any reasonable workspace. The caller-side `tools + system` prefix that wraps the response (sized by the MCP tool schema and the calling agent's own system prompt) is what clears the Anthropic caching minimums. See `11_inference_endpoint.md` for the full caching strategy.

### L2, L3 — on-demand navigation, not pre-loaded

The agent's `list`, `grep`, `search`, `read`, `follow`, `events`, `timeline`, `history`, `overview` tools cover L2 (topic-filtered retrieval) and L3 (full semantic navigation) on demand. We do not pre-load either tier. This is the cleanest expression of the agent-as-retriever principle.

### Budget enforcement

The `guide()` tool has hard output-token-count assertions. A workspace whose identity.md or SKILL.md grows unbounded trips an error that tells the user to prune. From Claude Code's best-practice rule (`research/raw/24_anthropic_claude_code_best_practices.md`): *"Bloated CLAUDE.md files cause Claude to ignore your actual instructions!"*

## Self-awareness — how "update their docs" actually works

User says: *"A new infrastructure RFC dropped for Acme. Please ingest it and update any docs that are affected."*

The agent needs to know what *it* produced before to decide what to update. This works because:

1. The wiki IS the memory. Every past ingest wrote pages; every page has `Sources` metadata and footnotes. Reading the wiki tells the agent what it has done.
2. `wiki/log.md` is the append-only trail. Parseable entries (`## [YYYY-MM-DD] ingest | RFC 0034 | touched: contracts/sla.md, infra/auth.md`) give a fast index of past activity.
3. The `wiki_log_entries` SQLite table stores the same information structured, so the agent can ask `search(kind="log", after="2026-04-01")` without parsing markdown.
4. The `wiki_claim_provenance` table links every citation in a wiki page to the raw source it came from. When a new source supersedes an old one, the agent finds the old page via provenance and rewrites the affected section.

The agent does not need a separate "memory layer." Its memory is the wiki plus the log plus the provenance index — all already on disk, all already in SQLite.

## What the agent can do

Three operations, Karpathy's original set. Each is a workflow, not a single tool call.

### Ingest
Turn raw sources into wiki pages, cascading related updates.

1. Pick the raw source(s) to ingest (by path, tag, or "pending").
2. `read()` raw content in chunks if large.
3. Decide: merge into existing article, or create new.
4. `write(create)` / `write(str_replace)` for each affected page.
5. Cascade: `search()` for related pages, update any materially affected.
6. Update `wiki/overview.md` with new source count, key findings, recent updates.
7. `write(append)` to `wiki/log.md` with `## [YYYY-MM-DD] ingest | <title>` + list of touched pages.
8. MCP tool writes a structured row to `wiki_log_entries` automatically on each log append.

Ingest is atomic-per-source: the log entry is the last step, so a partial ingest is detectable on next session.

### Query
Answer from the wiki, not training knowledge.

1. Read `wiki/overview.md` and `wiki/index.md` to orient.
2. `search()` for relevant terms.
3. `read()` top candidates.
4. Synthesize an answer with citations.
5. **Do not write** unless the user says "save this" — then file it as an archive page (`wiki/archives/<slug>.md`, immutable) and log it.

### Lint
Find and fix wiki rot. **Heuristic checks are delegated to the hostile verifier** (`13_hostile_verifier.md`) to avoid the same-model confirmation bias the `ai-engineer` review flagged in §3.3 — the writer cannot reliably critique its own prior writes; a fresh-context, hostile-prompted verifier can.

Deterministic fixes (auto-applied by the writer, no LLM judgment):
- Missing index entries → added.
- Broken internal links with exactly one candidate target → fixed.
- Missing see-also links between same-topic pages → added.
- Orphan concept pages → flagged and linked from the index.
- Verbatim quote anchor hash mismatches → flagged as `source_drifted`, never silently re-anchored.

Heuristic findings (delegated to the verifier; the verifier's verdict gates the lint run's commit):
- **Contradictions between pages** — the verifier compares claim sets across pages on the same topic. Per the convergence policy in `15_cascade_and_convergence.md`, real contradictions must be hedged with `::: disputed` markers; pages that contradict without the marker are a verifier reject.
- **Stale claims superseded by newer sources** — detected via `wiki_claim_provenance` + `documents.superseded_by`; verifier votes whether the supersession was applied with the convergence policy.
- **Missing pages for concepts mentioned but never defined** — verifier flags as `degraded`, never `reject`.
- **Archive pages whose cited sources have been updated since archival** — verifier flags; archives are immutable point-in-time snapshots so the answer is always "leave archived, surface the drift".

Lint runs are themselves staged runs (`run_type = 'lint'`) and pass through the same verifier path as ingest. Every lint run ends with an entry in `wiki_log_entries` and a log line in `verifier-YYYY-MM-DD.jsonl`. Every auto-fix is logged with the diff so the user can audit. The lint operation also feeds the **M5 self-consistency** metric in `14_evaluation_scaffold.md`.

## Tool surface (MCP) — navigation primitives, not a search engine

The guiding principle, grounded in `research/reference/12_agentic_retrieval.md`: **the agent is the retriever**. Our tools are composable navigation primitives. The agent decides what to read and in what order; we never push pre-retrieved content at it.

Every tool accepts a `workspace: str` argument and operates on exactly one workspace per call. Two launch modes:

- **Open mode** (`alexandria mcp serve`) — all workspaces accessible, `workspace` required on every call.
- **Pinned mode** (`alexandria mcp serve --workspace <slug>`) — locked to one workspace; `workspace` defaults to the pinned slug and any other value is rejected.

Transports:
- **stdio** (Claude Code, Cursor, Codex, Claude Desktop, Windsurf) — client launches the subprocess. No daemon.
- **HTTP + SSE** (Claude.ai web, remote clients) — daemon serves `http://localhost:<port>/mcp/<slug>` in pinned mode or `http://localhost:<port>/mcp` in open mode.

### The nine primitives

| Tool | Purpose | Analogue |
|---|---|---|
| `guide` | Orient. Returns L0 (identity, ≤500 output tokens) + L1 (essential state, ≤1500 output tokens). Called first every session. **Stable prefix designed for prompt caching** — see `11_inference_endpoint.md` and the L0/L1 specification below. | Claude Code's `CLAUDE.md` loading |
| `overview` | **Cold-start silhouette.** One call returns: directory tree (depth 2) + last 20 wiki page titles + event counts per source (last 7 days) + pinned pages + token estimates. Collapses 3-8 wasted exploration turns into one call. | `ls -la` + `git status` + `git log --oneline -20` combined |
| `list` | Structural browse. Glob-aware. `path="*.md"`, `path="/wiki/concepts/*"`, etc. | Glob |
| `grep` | Regex / exact-match pattern search across files. The sharp tool for error codes, quoted phrases, symbol names. | ripgrep |
| `search` | FTS5 keyword search with ranking + path scoping + tag filter. The broad tool for "pages about X." **One primitive among several — not the retriever.** | Keyword search |
| `read` | Fetch content. Single file or glob batch. Page ranges, sections, optional images. **Staging-aware** — when called inside a verifier run, returns staged content for paths under `runs/<run_id>/staged/` so the verifier reviews exactly what would land in the wiki. | Read |
| `follow` | Jump from a wiki page's footnote `[^N]` to the cited raw source via `wiki_claim_provenance`. First-class citation walk. Now includes the verbatim quote span and its hash anchor (see `13_hostile_verifier.md`). | Link traversal |
| `history` | Structured query over `wiki_log_entries` and `runs`: op, date range, touched documents, verifier verdict. The self-awareness accessor. | — |
| `write` | `create` / `str_replace` / `append`. **Stages writes into `runs/<run_id>/staged/`, never directly into `wiki/`.** Validates citations + verbatim quote anchors, rejects writes to `raw/`. The actual `wiki/` commit happens only after the hostile verifier (`13_hostile_verifier.md`) votes `commit`. | — |
| `delete` | Soft-delete to `.trash/`. Protects structural files. Same staged-run semantics as `write`. | — |
| `sources` | Read-only list of configured adapters + sync state + pending-to-ingest counts. Never returns credentials (see `18_secrets_and_hooks.md`). | — |
| `subscriptions` | Read-only pending subscription items. | — |
| `events` | Structured query over the event layer (GitHub / Calendar / Gmail / Slack / Discord / cloud activity). Filters by source, type, actor, time window, cross-stream `refs`. | Defined in `10_event_streams.md` |
| `timeline` | Pre-grouped summary of activity across event streams at day/week/month granularity. The entry point for "how did this project evolve" questions. | Defined in `10_event_streams.md` |
| `eval` | Read-only access to evaluation metric runs. Parameters: `metric ∈ {M1,M2,M3,M4,M5,all}`, `since`, `action ∈ {run,report}`. Triggers a daemon job; does not modify the wiki. | Defined in `14_evaluation_scaffold.md` |
| `git_log` | Run `git log` against a workspace-local git clone with filters (`since`, `until`, `path`, `grep`, `author`). Returns matching commits. | Git commit DAG navigation — primitive, not pipeline |
| `git_show` | Fetch a specific commit's full diff from a workspace-local clone. | `git show <sha>` |
| `git_blame` | Line-level authorship for a file in a workspace-local clone. | `git blame` |
| `why` | **Belief explainability.** Resolve a query (belief_id, subject, topic, or free-text) to one or more current beliefs and their supersession history. Returns supporting verbatim source quotes with deterministic hash verification flags. The single tool that answers *"why do I believe X?"* and *"what did I think in April?"*. | Defined in `19_belief_revision.md` |

### The retrieval pattern (explicit)

When the user asks a question, the agent's loop is:

1. `guide()` — orient.
2. `read("/wiki/overview.md")` + `read("/wiki/index.md")` — understand the shape.
3. `search(query=...)` or `grep(pattern=...)` or `list(path=...)` — narrow the candidate set using whichever primitive fits the question.
4. `read(path=..., pages/sections)` — pull only the content worth the context cost.
5. `follow(from_page, footnote_id)` when a cited raw source is needed.
6. Iterate: after each read, decide what is still missing, pick the next primitive.
7. Synthesize an answer with citations. Optionally `write` an archive.

This is dynamic multi-step search, exactly in the sense Anthropic uses in *Building a multi-agent research system* (`research/raw/23_*`). The pattern is **not** "run retrieval once, stuff results into context, generate."

### Subagents and context management

Subagents are the answer to "this question spans ten topics and I'd poison my context reading them all." The MCP client (Claude Code, Claude.ai) is responsible for spawning subagents; our MCP server is responsible for being safely re-entrant under concurrent calls from the same workspace. Each subagent gets its own context window, explores one topic, returns a condensed summary to the lead agent. This is the Claude Code playbook applied to knowledge bases.

### Engineering requirements from the multi-agent literature

Anthropic's multi-agent research post (distilled in `research/reference/13_agentic_retrieval_design_space.md`) names five lessons that directly shape how we design the MCP tool surface:

1. **Tool descriptions must be specific.** Vague descriptions make subagents pick the wrong tool. Every registered tool ships with usage examples in its description, not just a one-liner.
2. **Scale effort to query complexity via prompt rules.** `guide()` includes explicit guidance on when a quick `read` is enough versus when to go deep across multiple pages.
3. **External memory handles context limits.** `wiki/log.md` + `wiki_log_entries` **is** the external memory. Fresh subagents read recent log entries via `history()` to pick up where a previous session left off.
4. **Subagents write directly, not via the coordinator.** Every MCP tool call hits alexandria's filesystem and SQLite directly. No "telephone" relay through the lead agent. The MCP server is re-entrant so parallel subagents can write concurrently without corruption.
5. **Production tracing is mandatory.** Every tool call is logged to `~/.alexandria/logs/mcp-<date>.jsonl` with `{ts, workspace, tool, args_hash, latency_ms, result}`. This is not optional — non-determinism in agent sessions makes debugging impossible without it.

See `08_mcp_integration.md` for transports, client configs, and auth.

*[Older summary table removed — superseded by the comprehensive table above. The canonical tool surface is the table at the top of this section.]*

The agent **cannot** configure sources, subscriptions, or workspaces. Those are user actions via the CLI or web UI.

## Hard guardrails (enforced in code, not prompt)

1. **Path ACL.** `write` rejects any path that doesn't start with `wiki/`. All raw paths are read-only.
2. **Workspace boundary.** Every path is resolved against the workspace root; symlinks and `..` traversal are rejected.
3. **Citation check (deterministic + semantic).** Wiki pages with body content must have at least one footnote citation. Structural pages (`overview`, `index`, `log`, archives) are exempt. **Each footnote must include a verbatim quote span from the cited source**, stored in `wiki_claim_provenance.source_quote` with a `source_quote_hash` (sha256). The deterministic check verifies the hash against the live raw source on every write — a fabricated citation fails this check without any LLM judgment. The semantic check (does the quote actually support the claim?) is performed by the hostile verifier in `13_hostile_verifier.md`. Both must pass for the run to commit.
4. **Template check.** `create` parses the frontmatter and rejects pages missing required fields (title, sources line).
5. **Quota check.** Before every `create`, compare against per-workspace page quota.
6. **Protected files.** `delete` refuses `overview.md`, `index.md`, `log.md`.
7. **Exactly-one-match replace.** `str_replace` errors if `old_text` is missing or matches multiple times. Forces the agent to read before editing.
8. **Log linkage.** When the agent appends to `log.md`, the tool parses the header and writes a corresponding row to `wiki_log_entries`. If the header is unparseable, the write is rejected.

## System prompt shape

`guide()` returns something like this, abbreviated:

```markdown
# You are the guardian of workspace: {name}

## The contract
- You write and maintain the wiki. The user reads and asks questions.
- Raw sources are immutable. You read them. You never write them.
- Wiki pages live under wiki/. You own that namespace entirely.
- Every factual claim on a wiki page must cite a source via footnote:
    [^1]: source-filename.pdf, p.3

## The operations
You know three operations: ingest, query, lint. Every user request
decomposes into one of these.

## Workspace schema
- wiki/overview.md    — hub page, update on every ingest
- wiki/index.md       — table of contents, update on every ingest/lint
- wiki/log.md         — append-only operation log, parseable headers
- wiki/<topic>/       — one level of topic directories only
- wiki/archives/      — immutable query snapshots

## Your tools
guide, search, read, write, delete, sources, subscriptions, history.

## Current state
Workspace: {name} ({description})
Raw sources: {count} ({new_since_last_ingest} pending ingest)
Wiki pages: {count}
Pending subscription items: {count}

## Recent activity (last 10 log entries)
{parsed log}

## Your recent work
{self-awareness summary from wiki_log_entries}
```

The contract is versioned (`contract_version` in workspace config). Changing the global schema bumps the version; existing workspaces keep their pinned version until explicitly migrated.

## What the agent does NOT do

- **Does not auto-ingest.** The daemon pulls new content into `raw/`, but only the user (in chat) triggers ingest. Rationale: preserves user intent + bounds token spend. Exception: `alexandria automation create --on "subscription" --run "ingest"` can opt a specific workspace into auto-ingest after the user sets it up explicitly.
- **Does not configure sources or subscriptions.** CLI/UI only.
- **Does not share wikis.** Not a concept here.
- **Does not run code or shell.** Read/write markdown only.
- **Does not make web calls.** Sources are fetched by trusted adapters in sync workers, never by the agent's tools.
