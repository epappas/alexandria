# 01 — Vision and Principles

> **Cites:** `research/reference/01_karpathy_pattern.md`, `research/reference/03_astrohan_skill.md`, `research/reference/07_why_post_code.md`

## Vision

`llmwiki` is a **local-first, single-user Python knowledge engine**. It accumulates, structures, and serves the user's gathered knowledge — source documents, compiled wiki pages, event streams from projects and communications — so that the user can **retroactively query, retrieve, and review** everything they have ever fed into it, across months or years. The wiki lives on disk under `~/.llmwiki/` (configurable) so it is the user's data, period.

This is Karpathy's LLM Wiki pattern, operationalized as a personal tool. Not a SaaS.

### The five capabilities llmwiki provides

1. **Ingestions** — pulling content in. Source adapters (local files, Obsidian, Notion, GitHub docs, arXiv papers, S3/Drive), subscription adapters (RSS/Atom, Substack, YouTube, newsletters via IMAP), and event-stream adapters (GitHub activity, Google Calendar, Gmail, Slack, Discord, cloud-storage changes). Raw material is captured, normalized, and stored with full provenance.
2. **Knowledge structuring** — compiling that raw material into a persistent wiki. Concept pages, entity pages, cross-references, cited claims, cascade updates, scheduled temporal digests of event streams. The wiki accumulates and compounds.
3. **Questions** — answering them against the accumulated knowledge. Not just "what do I know about X" but *"what did I learn about X last month"* and *"what has changed since Q1"* — the retroactive query is the load-bearing use case.
4. **Explorations** — navigation primitives the agent composes into research workflows. `list`, `grep`, `search`, `read`, `follow`, `events`, `timeline`, `history`. The agent walks the knowledge; llmwiki gives it the primitives to walk with.
5. **Subscriptions** — continuously keeping the knowledge current. Feeds for blogs / newsletters / videos; event streams for project activity; all accumulating into the same store, all queryable retroactively.

### llmwiki is a knowledge engine, not a coding agent

llmwiki is **not** Claude Code, OpenCode, Cursor, Copilot, or any other interactive agent. Those tools already exist, they are excellent at what they do, and llmwiki has no interest in replacing them. llmwiki **is the knowledge engine those agents connect to via MCP** (`08_mcp_integration.md`). When you ask Claude Code "what happened on the auth refactor last month," Claude Code is the agent running the reasoning loop; llmwiki is the engine that supplies the history, the commits, the meeting notes, the Slack discussions, the compiled wiki pages, and the navigation primitives Claude Code uses to find the answer.

The division of labor is sharp:

- **The connected MCP agent** (Claude Code / Cursor / Claude.ai / Codex / Windsurf) runs the conversation, holds the user's attention, streams responses, renders tool calls, takes input. It is the interactive surface.
- **llmwiki** accumulates knowledge, maintains structure, enforces citations, polls sources, ingests events, indexes everything for fast agentic retrieval, and serves it all through a precise MCP tool surface. It is the memory and the retrieval layer.

The one place llmwiki runs an LLM directly is **unattended background work** — scheduled temporal synthesis from event streams, scheduled lint, and CLI batch operations (`llmwiki synthesize`, `llmwiki lint --run`). That runner is a bounded, budgeted, opt-in mini agent loop with no user interaction, specified in `11_inference_endpoint.md`. Everything else happens in the connected client.

### Retroactive query is the load-bearing use case

The value of a knowledge engine is cumulative, not instantaneous. A fresh install adds nothing the user does not already know. Six months of running, polling subscriptions, syncing GitHub activity, ingesting meetings, and compiling wiki pages — that is when it starts to be indispensable. By then the engine holds:

- Every blog post, paper, and newsletter the user captured.
- Every commit, PR, issue, and release on every tracked repo.
- Every meeting, every calendar invite, every subject-matter email thread.
- Every Slack discussion from the relevant channels and DMs.
- Every compiled wiki page that synthesizes the above into durable concepts and entities.
- Every weekly timeline digest that narrates the changes.

The user can ask Claude Code: *"What did we decide about auth back in February?"* and Claude Code uses llmwiki's tools to walk the event stream (the meeting where it was decided, the Slack discussion leading to the decision, the PR that implemented it, the wiki page that summarized it at the time, the revision that changed it later) and returns a grounded, cited, temporally-correct answer. That is what the architecture is for.

### Implementation invariants

- One install per user, per machine.
- Zero accounts, zero hosting.
- Markdown files on disk are the source of truth for the document layer; SQLite is the source of truth for the event layer (see invariant 11).
- A small local daemon (optional) runs scheduled syncs, subscription polls, event-stream ingestion, scheduled temporal synthesis, and the MCP server over HTTP.
- The stdio MCP mode (`llmwiki mcp serve`) works without the daemon at all.

## Why this instead of RAG

| RAG | llmwiki |
|---|---|
| Knowledge lives in embeddings | Knowledge lives in curated markdown |
| Synthesis happens at query time | Synthesis happens at ingest + maintenance |
| Every query re-discovers relationships | Relationships are stored as cross-references |
| Black-box retrieval | Every claim traceable to a source |
| Good for millions of docs | Good for dozens to low thousands |

Personal-scale knowledge. Hundreds of sources per workspace, tens of workspaces per user.

## The three layers (non-negotiable)

1. **Raw.** Immutable source material. The agent reads, never writes. Stored verbatim as files on disk plus a SQLite row with normalized metadata.
2. **Wiki.** Compiled markdown pages. The agent owns this entirely. Organized as `wiki/<topic>/<concept|entity>.md` with mandatory structural files `wiki/overview.md`, `wiki/index.md`, `wiki/log.md`.
3. **Schema.** The contract taught to the agent on every session — directory conventions, file templates, operation workflows. A markdown document (`SKILL.md` or equivalent) the agent reads before acting.

## Workspaces — scoping knowledge

The user has more than one body of knowledge. `llmwiki` recognizes two kinds:

- **Global workspace** (`~/.llmwiki/workspaces/global/`) — the user's personal general knowledge. Always exists. Created at `llmwiki init`.
- **Project workspaces** (`~/.llmwiki/workspaces/<name>/`) — one per project, customer, client, research topic, or any coherent body of work. Created with `llmwiki project create <name>`.

Each workspace is a self-contained `raw/` + `wiki/` + its own sources, subscriptions, and log. The agent operates on **one workspace at a time**. Workspace selection is an explicit user action, not a runtime guess. See `03_workspaces_and_scopes.md`.

## What the agent knows about itself

The guardian is **aware of its own produced work**. Every time it runs, it reads:

1. The current workspace's `wiki/index.md`, `wiki/overview.md`, and last N entries of `wiki/log.md`.
2. A structured session log from SQLite — recent ingest/query/lint operations with the files they touched.

This is how "given the work done for customer X, update their docs when a new source arrives" actually works: the agent sees that a contract document exists, sees that it was updated last Tuesday after an ingest, sees the log entry, and updates exactly the pages that referenced the now-superseded claim.

No separate "memory" layer. The wiki **is** the memory. The log is the memory's index.

## Retrieval is a tool, not a pipeline

llmwiki does **not** use retrieval-augmented generation. There is no vector store, no pre-chunked embedding index, no top-k retrieval pipeline. This is a deliberate design commitment grounded in Anthropic's own published guidance and a survey-level reading of the 2025–2026 retrieval literature (see `research/reference/12_agentic_retrieval.md` and `research/reference/13_agentic_retrieval_design_space.md`).

The sharpest framing comes from the gist at `raw/26_*`:

> *"Retrieval is becoming a tool, not a pipeline. The agent decides when to retrieve, from what index, using what strategy — and that decision is itself part of the reasoning loop."*

llmwiki is **one retrieval tool among many** that an agent composes via MCP. The agent chooses when to call us, which of our primitives to use, and how to combine our output with other MCP tools (web search, other wikis, code search, etc.). We do not own the session and we do not pretend to be "the retrieval layer." We are a sharply-scoped navigation surface over a compiled personal wiki, exposed through MCP.

Anthropic, in *Building a multi-agent research system*:

> "Traditional approaches using Retrieval Augmented Generation (RAG) use static retrieval ... our architecture uses a multi-step search that dynamically finds relevant information, adapts to new findings, and analyzes results to formulate high-quality answers."

Karpathy, in the tweet this project is based on:

> "I thought I had to reach for fancy RAG, but the LLM has been pretty good about auto-maintaining index files and brief summaries of all the documents and it reads all the important related data fairly easily at this ~small scale."

**The guardian agent is the retriever.** Our job is to expose good navigation primitives and get out of the way. The agent orients itself through `guide()`, navigates with `list` / `grep` / `search`, reads what it decides is worth the context cost, follows citations with `follow`, and synthesizes. When a question is too wide for one context window, it spawns a subagent — the same pattern Claude Code uses on codebases.

This is not "we'll add vectors later when we scale." At the scale llmwiki targets (tens to a few thousand pages per workspace) the agent can reach every relevant page through navigation. Beyond that scale, the fix is better orientation documents and smarter subagent patterns, not a parallel vector pipeline.

## Invariants

These rules make the wiki trustworthy. Every feature must preserve them.

1. **Single user.** One OS user, one `~/.llmwiki/`. No tenancy, no auth, no sessions. If two people want two wikis, they use two machine accounts.
2. **Raw immutability.** Once a source lands, its file is frozen. Re-sync creates a new version record, never mutates the existing file.
3. **Agent cannot write raw.** Guardian has read access to `raw/` and read-write to `wiki/`. Enforced in the tool layer, not just the prompt.
4. **Wiki pages cite sources.** Every factual claim uses a footnote citation `[^1]: filename, p.3`. Writes without citations fail validation (structural pages exempted).
5. **One workspace per agent session.** The agent cannot read or write outside the workspace it was started in.
6. **Every ingest updates `log.md` and `overview.md`.** The agent cannot "forget" to log or to refresh the hub page.
7. **Cascade updates are mandatory on ingest.** A source that introduces a claim triggers a review of related pages. "One page per source" is the failure mode that kills personal wikis.
8. **Archives are immutable snapshots.** Once a query answer is archived, it is never cascade-updated.
9. **Vault separation.** The agent never writes into a source vault (Obsidian, Notion, Drive, git). Those are read-only sources. The wiki always lives in our store. (*Steph Ango's rule — see `reference/07_why_post_code.md`.*)
10. **Determinism over autonomy where trust matters.** Lint auto-fixes are limited to unambiguous rules (broken links with a single candidate, missing index entries). Judgment calls (contradictions, stale claims) are reported, not silently "resolved."
11. **Files first for the document layer; APIs-of-record for the event layer.** Two domains inside a workspace:
    - **Document layer** (`raw/` + `wiki/`) — filesystem is the source of truth. SQLite is a materialized view. Deleting `~/.llmwiki/` and running `llmwiki reindex` reconstructs the SQLite state. The user can `git init` the directory, version it, Syncthing it, or open it in Obsidian.
    - **Event layer** (SQLite `events` table family + derived digest files under `raw/timeline/`) — SQLite is the source of truth for the local copy. Events are born from API calls, not files. Reconstruction is via API replay from the source platforms, subject to per-platform retention limits (e.g., GitHub Events API's 30-day cap, Slack free tier's 90-day window — see `10_event_streams.md`).
    Both layers live under the same workspace; the agent reads each through different MCP tools and the wiki layer can cross-reference both.
12. **Subscriptions are just scheduled sources.** A newsletter feed and a Twitter feed are flavors of source adapters with a poll cadence. No special-case code paths.
13. **Agent-as-retriever.** No embedding pipeline. No vector index. No top-k retrieval. Retrieval is the agent's reasoning loop composed over navigation primitives (`guide`, `list`, `grep`, `search`, `read`, `follow`). If a problem can't be solved with those primitives + subagents, the fix is better primitives, not a parallel retrieval system.
14. **llmwiki is a knowledge engine, not a coding agent.** Interactive conversations happen in connected MCP agents — Claude Code, Cursor, Claude.ai, Codex, Claude Desktop, Windsurf, Zed, OpenCode, Continue — not in llmwiki. Those tools already handle streaming, context management, user input, and tool-use rendering; llmwiki does not compete with them. llmwiki exposes knowledge through a precise MCP tool surface (`08_mcp_integration.md`) and otherwise stays out of the way. The one case where llmwiki itself runs an agent loop is **unattended daemon work** — scheduled temporal synthesis, scheduled lint, CLI batch operations — and that runner is a bounded, budgeted, opt-in mini loop with no user interaction. See `11_inference_endpoint.md`.
15. **Retroactive query is the load-bearing use case.** Every feature is evaluated against "does this make the user's knowledge *six months from now* more queryable, retrievable, and reviewable than it is today?" Features that don't accumulate value over time (flashy demos, one-shot reports) are rejected. Features that compound — subscriptions, event streams, structured logs, provenance links, scheduled digests, conversation capture — are prioritized.
16. **Every wiki write passes through a hostile verifier.** The writer and the verifier are distinct agent runs — fresh context, read-only tools, adversarial prompt. Writes are not committed to the wiki layer until the verifier's verdict is `commit` or the user manually overrides via `llmwiki verify override`. Defined in `13_hostile_verifier.md`. Mandatory exceptions are explicit and small (structural log appends, user `--no-verify`, draft-only mode).
17. **Cascade is atomic.** A write plan that touches N pages either commits all N or none. Staged writes live in `~/.llmwiki/runs/<run_id>/staged/` and are moved into `wiki/` only after the verifier passes. Half-cascades cannot exist. Defined in `13_hostile_verifier.md` and `15_cascade_and_convergence.md`. The same staged-run mechanism is reused for synthesis crash recovery and budget-stop rollback — one abstraction, four concerns closed.
18. **Convergence is hedged with dated markers.** When a new source contradicts an existing claim, the guardian preserves both with a `::: disputed` marker and an "Updated YYYY-MM-DD per <source>" annotation. *"What did I think in April?"* must remain answerable. Defined in `15_cascade_and_convergence.md`. Silently overwriting a claim is a verifier reject.
19. **Evaluation is continuous and gated.** The engine runs five metrics (M1 citation fidelity, M2 cascade coverage, M3 retroactive query benchmark, M4 cost characterization, M5 self-consistency) on a schedule. Broken M1 or M2 blocks scheduled synthesis until manually acknowledged. New source adapters are blocked until M1+M2 are wired up and producing weekly reports. Defined in `14_evaluation_scaffold.md`. The retroactive-query invariant is now testable.
20. **Beliefs are explainable and traceable.** Every substantive assertion in the wiki is recorded as a structured belief with stable identity, supersession history, and a provenance chain to a verbatim source quote whose hash is checked deterministically against the live raw file. The user can ask *"why do I believe X?"* and get the full chain — current belief, supporting sources with verbatim quotes, prior superseded beliefs, the run that changed the wiki's mind, and the reason for the change — in one `why()` tool call. Beliefs supersede on cascade contradictions per `15_cascade_and_convergence.md`; the historical chain is never deleted, only marked. Defined in `19_belief_revision.md`. *"What did I think in April?"* is now a single SQL filter.

## A sibling project, and what we learned from it

[MemPalace](https://github.com/mempalace/mempalace) is a local-first personal AI memory system that shares many of llmwiki's values — local-first, MCP-first, Zettelkasten-inspired, zero-API-mandatory, explicitly not a chat client. We diverge on the load-bearing retrieval question (mempalace uses vector embeddings with serious benchmark numbers — 96.6% R@5 on LongMemEval raw; llmwiki uses agentic navigation per invariant #13) and on the storage unit (mempalace stores verbatim drawers / chunks; llmwiki compiles synthesized wiki pages). Neither bet is wrong; they target different failure modes and a sophisticated user could run both side-by-side.

Three ideas from mempalace directly strengthen llmwiki and are adopted in the architecture:

1. **Tiered wake-up (`guide()` as L0/L1).** Mempalace's `layers.py` formalizes session start as L0 (identity, ~100 tok) + L1 (essential story, ~500-800 tok) = ~600-900 token wake-up with 95% of context left free. llmwiki's `guide()` is now formally tiered with hard budgets (L0 ≤ 500 tok, L1 ≤ 1500 tok, combined ≤ 2000). See `04_guardian_agent.md` — the tiering section.
2. **Conversation transcript capture.** Mempalace's `convo_miner.py` ingests Claude Code / ChatGPT / Slack / markdown / plain-text conversation history. llmwiki adds a `conversation` adapter for the same formats plus Cursor and Codex. Conversations land as markdown documents in `raw/conversations/` AND as structured events in the `events` table (hybrid SOURCE + EVENT_STREAM). See `12_conversation_capture.md`.
3. **Auto-save hooks.** Mempalace installs Claude Code `Stop` and `PreCompact` hooks that trigger `mempalace mine` in the background. llmwiki ships the same pattern for Claude Code, Cursor, and Codex: `llmwiki hooks install claude-code` writes the hook block, a tiny bash script kicks off `llmwiki mine conversations --detach`, and the user's own thinking-with-AI sessions accumulate in the engine automatically. See `12_conversation_capture.md` — "Auto-save hooks."

The full comparison, three more deferred ideas, and the explicit non-adoptions (vectors, verbatim-chunk storage, first-class knowledge graph with PPR retrieval, AAAK compression) live in `research/reference/14_mempalace.md`. Read it alongside `research/raw/36_mempalace.md` before making any decision that touches conversation capture, the wake-up tiering, or the sibling-project framing.

## The contract, restated

> *"The LLM writes and maintains the wiki; the human reads and asks questions."*

We build the smallest local tool that makes this contract true across many workspaces, with pluggable sources and a self-aware agent.
