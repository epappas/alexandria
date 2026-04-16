# 06 — Data Model

> **Cites:** `research/reference/02_lucasastorian_impl.md`, `research/reference/03_astrohan_skill.md`, `research/reference/04_atomicmemory_compiler.md`

Files first, SQLite second. The filesystem is the source of truth. SQLite is a materialized view over it — if you delete `state.db`, `llmwiki reindex` rebuilds it from the files.

## On-disk layout

```
~/.llmwiki/                              # $LLMWIKI_HOME, configurable
├── config.toml                          # global config
├── state.db                             # SQLite index, provenance, sync state
├── secrets/                             # encrypted adapter credentials
│   └── <adapter-id>.enc
├── .trash/                              # soft-deletes moved here; gc'd on demand
│   └── <timestamp>/...
├── templates/                           # user overrides of packaged templates
│   └── workspaces/
└── workspaces/
    ├── global/
    │   ├── SKILL.md                     # agent contract for this workspace
    │   ├── config.toml                  # workspace settings
    │   ├── raw/
    │   │   ├── local/                   # one subdir per adapter instance
    │   │   ├── github/
    │   │   ├── notion/
    │   │   ├── papers/
    │   │   └── subscriptions/
    │   │       ├── newsletter/
    │   │       ├── twitter/
    │   │       └── rss/
    │   └── wiki/
    │       ├── overview.md              # mandatory hub
    │       ├── index.md                 # mandatory TOC
    │       ├── log.md                   # mandatory append-only log
    │       ├── concepts/
    │       │   └── <slug>.md
    │       ├── entities/
    │       │   └── <slug>.md
    │       └── archives/
    │           └── <slug>.md            # immutable query snapshots
    └── customer-acme/
        └── ...                          # same shape
```

## Why filesystem-first

1. **Portable.** The user can `git init ~/.llmwiki/`, back it up with Syncthing, move it to a new machine by copying the folder.
2. **Tool-compatible.** Obsidian opens any `workspaces/<slug>/wiki/` directly. So does `grep`, `ripgrep`, `vim`, and any markdown editor.
3. **Transparent.** The user can see what the agent wrote. No opaque database holding mysterious blobs.
4. **Recoverable.** If SQLite corrupts, `llmwiki reindex` rebuilds from files. If a markdown file is bad, the user can fix it in their editor.

## SQLite schema

SQLite runs in WAL mode. One file: `~/.llmwiki/state.db`. No per-workspace databases — a single schema indexes everything with a `workspace` column.

### `workspaces`
```sql
CREATE TABLE workspaces (
  slug            TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT,
  path            TEXT NOT NULL,           -- absolute path to workspace dir
  contract_version TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
```

### `source_adapters`
```sql
CREATE TABLE source_adapters (
  id              TEXT PRIMARY KEY,        -- UUID
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  type            TEXT NOT NULL,           -- 'local'|'notion'|'github'|...
  kind            TEXT NOT NULL,           -- 'source'|'subscription'|'storage'
  name            TEXT NOT NULL,
  config_ref      TEXT NOT NULL,           -- path to encrypted config in secrets/
  cadence_seconds INTEGER,                 -- NULL = manual only
  mode            TEXT NOT NULL DEFAULT 'read',  -- 'read'|'push'|'read-push'
  status          TEXT NOT NULL DEFAULT 'active',
  last_run_at     TEXT,
  last_error      TEXT,
  created_at      TEXT NOT NULL
);
```

### `source_runs`
```sql
CREATE TABLE source_runs (
  id              TEXT PRIMARY KEY,
  adapter_id      TEXT NOT NULL REFERENCES source_adapters(id) ON DELETE CASCADE,
  started_at      TEXT NOT NULL,
  finished_at     TEXT,
  status          TEXT NOT NULL,           -- 'running'|'success'|'error'|'partial'
  items_fetched   INTEGER DEFAULT 0,
  items_new       INTEGER DEFAULT 0,
  items_updated   INTEGER DEFAULT 0,
  items_skipped   INTEGER DEFAULT 0,
  error_message   TEXT
);
```

### `documents`
One row per file in `raw/` or `wiki/`. The file on disk is authoritative; this table is a materialized view for search and metadata.

```sql
CREATE TABLE documents (
  id              TEXT PRIMARY KEY,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  layer           TEXT NOT NULL,           -- 'raw' | 'wiki'
  path            TEXT NOT NULL,           -- relative to workspace root, POSIX style
  filename        TEXT NOT NULL,
  title           TEXT,
  file_type       TEXT NOT NULL,
  content         TEXT,                    -- extracted text for search (may be NULL for binaries)
  content_hash    TEXT NOT NULL,           -- sha256 of the file on disk
  size_bytes      INTEGER NOT NULL,
  page_count      INTEGER,

  adapter_id      TEXT REFERENCES source_adapters(id) ON DELETE SET NULL,
  source_run_id   TEXT REFERENCES source_runs(id)      ON DELETE SET NULL,
  external_id     TEXT,                    -- stable ID in source system
  original_url    TEXT,
  fetched_at      TEXT,
  published_at    TEXT,

  tags            TEXT NOT NULL DEFAULT '[]',   -- JSON array
  metadata        TEXT,                    -- JSON blob
  superseded_by   TEXT REFERENCES documents(id),
  pending_ingest  INTEGER NOT NULL DEFAULT 0,   -- 1 for raw items not yet compiled

  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,

  UNIQUE(workspace, path, filename)
);

CREATE INDEX idx_documents_workspace_layer ON documents(workspace, layer);
CREATE INDEX idx_documents_pending         ON documents(workspace) WHERE pending_ingest = 1;
CREATE INDEX idx_documents_adapter         ON documents(adapter_id);
```

### FTS5 search index
```sql
CREATE VIRTUAL TABLE documents_fts USING fts5(
  title, content, tags, content='documents', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```
Triggers keep `documents_fts` in sync with `documents`. Search queries go through FTS5 for keyword/phrase matching.

### No chunks, no embeddings, no vectors — ever

llmwiki does not chunk documents, does not compute embeddings, and does not store vectors. There is no `document_chunks` table, no embedding column, no HNSW index. Retrieval is **agentic** — the guardian agent uses `list` / `grep` / `search` (FTS5) / `read` / `follow` as navigation primitives and composes them in a reasoning loop. The agent is the retriever.

This is a deliberate commitment grounded in Karpathy's original tweet (*"I thought I had to reach for fancy RAG, but the LLM has been pretty good about auto-maintaining index files and brief summaries"*) and Anthropic's published guidance (*"Traditional approaches using Retrieval Augmented Generation (RAG) use static retrieval ... our architecture uses a multi-step search that dynamically finds relevant information"*). See `research/reference/12_agentic_retrieval.md`.

If a future workspace grows past the point where FTS5 + grep + read are enough, the fix is sharper orientation documents and subagent patterns, not a parallel vector pipeline.

### `wiki_log_entries`
Structured mirror of `wiki/log.md`. The MCP `write` tool parses every append to the log and inserts a row here.

```sql
CREATE TABLE wiki_log_entries (
  id              TEXT PRIMARY KEY,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  op              TEXT NOT NULL,           -- 'ingest'|'query'|'lint'|'created'
  title           TEXT,
  touched         TEXT NOT NULL DEFAULT '[]',   -- JSON array of document paths
  details         TEXT,                    -- JSON
  created_at      TEXT NOT NULL
);

CREATE INDEX idx_wiki_log_workspace ON wiki_log_entries(workspace, created_at DESC);
```

This is what makes the agent's self-awareness fast: `history(workspace, op, after)` is a single indexed query.

### `wiki_claim_provenance`
Every footnote citation in a wiki page resolves to a `raw/` document. The write-tool records the resolution here. As of `13_hostile_verifier.md`, every citation MUST include a verbatim quote span and its hash so the deterministic citation check (no LLM judgment) can detect fabrication and source drift.

```sql
CREATE TABLE wiki_claim_provenance (
  id                  TEXT PRIMARY KEY,
  workspace           TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  wiki_document_id    TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  footnote_id         TEXT NOT NULL,           -- e.g. "1" from "[^1]"
  raw_document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_hint           INTEGER,                 -- optional page number from citation
  source_quote        TEXT NOT NULL,           -- verbatim span from the source (REQUIRED)
  source_quote_hash   TEXT NOT NULL,           -- sha256 of source_quote
  source_quote_offset INTEGER,                 -- char offset in source file (best-effort)
  created_at          TEXT NOT NULL,
  UNIQUE(wiki_document_id, footnote_id)
);

CREATE INDEX idx_provenance_raw ON wiki_claim_provenance(raw_document_id);
CREATE INDEX idx_provenance_quote_hash ON wiki_claim_provenance(source_quote_hash);
```

When lint runs, it joins this table against `documents.superseded_by` to find wiki pages whose cited sources have been replaced. The hostile verifier (`13_hostile_verifier.md`) uses the `source_quote_hash` for its deterministic check #3 — fail the run if `sha256(raw_file[offset : offset + len(source_quote)]) != source_quote_hash`.

### `runs` — staged write transactions
Every wiki write is wrapped in a run with one of five states. Defined in detail in `13_hostile_verifier.md`.

```sql
CREATE TABLE runs (
  run_id           TEXT PRIMARY KEY,
  workspace        TEXT NOT NULL REFERENCES workspaces(slug),
  triggered_by     TEXT NOT NULL,          -- 'mcp:<tool>' | 'cli:<cmd>' | 'daemon:<job>'
  run_type         TEXT NOT NULL,          -- 'ingest'|'cascade'|'synthesis'|'lint'|'archive'|'eval'|'rollback'
  status           TEXT NOT NULL,          -- 'pending'|'verifying'|'committed'|'rejected'|'abandoned'
  started_at       TEXT NOT NULL,
  ended_at         TEXT,
  verifier_preset  TEXT,
  verdict          TEXT,                   -- 'commit'|'reject'|'revise'|'commit_override'
  reject_reason    TEXT,
  loop_count       INTEGER NOT NULL DEFAULT 1,
  parent_run_id    TEXT REFERENCES runs(run_id),
  budget_input_tokens_used  INTEGER DEFAULT 0,
  budget_output_tokens_used INTEGER DEFAULT 0,
  budget_usd_used  REAL DEFAULT 0,
  CHECK (status IN ('pending','verifying','committed','rejected','abandoned'))
);

CREATE INDEX idx_runs_workspace_started ON runs(workspace, started_at DESC);
CREATE INDEX idx_runs_status_started    ON runs(status, started_at DESC);
CREATE INDEX idx_runs_parent            ON runs(parent_run_id);
```

`source_runs` (above) tracks external-API sync runs. `runs` tracks guardian write runs. Different concerns, different tables, no overlap.

### `eval_runs` and `eval_gold_queries`
Defined in `14_evaluation_scaffold.md`. M1-M5 metric runs and the user-seeded gold standard for M3.

```sql
CREATE TABLE eval_runs (
  run_id       TEXT PRIMARY KEY REFERENCES runs(run_id),
  workspace    TEXT NOT NULL REFERENCES workspaces(slug),
  metric       TEXT NOT NULL,        -- 'M1'|'M2'|'M3'|'M4'|'M5'
  run_at       TEXT NOT NULL,
  score        REAL,
  status       TEXT NOT NULL,        -- 'healthy'|'degraded'|'broken'
  tokens_used  INTEGER DEFAULT 0,
  usd_used     REAL DEFAULT 0,
  details      TEXT                  -- JSON
);

CREATE INDEX idx_eval_runs_workspace_metric ON eval_runs(workspace, metric, run_at DESC);

CREATE TABLE eval_gold_queries (
  id                 TEXT PRIMARY KEY,
  workspace          TEXT NOT NULL REFERENCES workspaces(slug),
  query              TEXT NOT NULL,
  expected_topics    TEXT NOT NULL,    -- JSON array
  expected_citations TEXT NOT NULL,    -- JSON array of raw file paths
  authored_at        TEXT NOT NULL,
  authored_by        TEXT NOT NULL,
  UNIQUE(workspace, query)
);
```

### `schema_migrations`
Defined in `16_operations_and_reliability.md`. Append-only ledger of every applied migration with sha256 tamper detection.

```sql
CREATE TABLE schema_migrations (
  version       INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  script_path   TEXT NOT NULL,
  script_sha256 TEXT NOT NULL,
  applied_at    TEXT NOT NULL,
  applied_by    TEXT NOT NULL  -- 'auto-on-startup'|'cli'|'manual'
);
```

`PRAGMA user_version` mirrors `MAX(version)`. The daemon refuses to start on a tampered checksum or missing migration.

### `daemon_heartbeats`
Defined in `16_operations_and_reliability.md`. Liveness for the supervised-subprocess model.

```sql
CREATE TABLE daemon_heartbeats (
  child_name   TEXT PRIMARY KEY,
  pid          INTEGER NOT NULL,
  started_at   TEXT NOT NULL,
  last_beat    TEXT NOT NULL,
  state        TEXT NOT NULL  -- 'starting'|'running'|'draining'|'failed'
);
```

### `capture_queue`
Defined in `18_secrets_and_hooks.md`. Per-session serialization for conversation capture concurrency.

```sql
CREATE TABLE capture_queue (
  session_id        TEXT PRIMARY KEY,
  workspace         TEXT NOT NULL REFERENCES workspaces(slug),
  client            TEXT NOT NULL,
  transcript_path   TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'queued',  -- 'queued'|'in_progress'|'done'|'failed'
  enqueued_at       TEXT NOT NULL,
  started_at        TEXT,
  completed_at      TEXT,
  last_content_hash TEXT,
  error             TEXT
);
```

### `mcp_session_log`
Defined in `12_conversation_capture.md` (MCP-side capture path) and `17_observability.md` (the JSONL log family is the on-disk source; this table is the queryable structured view). Every MCP tool call from every connected client lands as a row.

```sql
CREATE TABLE mcp_session_log (
  id              TEXT PRIMARY KEY,                -- UUID
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  session_id      TEXT NOT NULL,                   -- MCP session identifier (transport-provided or daemon-assigned)
  client_name     TEXT NOT NULL,                   -- 'claude-code'|'cursor'|'codex'|'claude-desktop'|'claude-web'|'windsurf'|'zed'|'continue'|'unknown'
  client_version  TEXT,
  caller_model    TEXT,                            -- model the client advertised, NULL if not advertised
  tool_name       TEXT NOT NULL,                   -- 'guide'|'read'|'write'|...
  redacted_args   TEXT,                            -- args with secrets redacted (queryable, not raw)
  tool_args_hash  TEXT NOT NULL,                   -- sha256(redacted_args) for dedup
  result_size_bytes INTEGER,
  result_summary  TEXT,                            -- one-line auto-generated summary
  latency_ms      INTEGER,
  run_id          TEXT REFERENCES runs(run_id),    -- NULL for read-only calls
  ts              TEXT NOT NULL                    -- ISO 8601, millisecond precision
);

CREATE INDEX idx_mcp_session_log_session  ON mcp_session_log(session_id, ts);
CREATE INDEX idx_mcp_session_log_workspace_ts ON mcp_session_log(workspace, ts DESC);
CREATE INDEX idx_mcp_session_log_tool     ON mcp_session_log(workspace, tool_name, ts DESC);
CREATE INDEX idx_mcp_session_log_client   ON mcp_session_log(workspace, client_name, ts DESC);
CREATE INDEX idx_mcp_session_log_run      ON mcp_session_log(run_id) WHERE run_id IS NOT NULL;
```

Reconciliation with file-based conversation capture: both paths use the same `session_id`. The file-based path produces markdown in `raw/conversations/<client>/<yyyy-mm-dd>-<session-id>.md` plus rows in `events` (with `source='conversation'`); the MCP-side path produces rows in `mcp_session_log`. Queries across both stores join on `session_id`.

For clients without hook support (Claude.ai web), the MCP-side log is the only capture available — and it captures **every** tool call regardless of the client's introspection capabilities, because the call traverses our process boundary. This closes the conversation-capture loop universally.

### `wiki_beliefs` and `wiki_beliefs_fts`
Defined in `19_belief_revision.md`. Beliefs are structured rows extracted from wiki pages at write time, with stable identity, supersession history, and a provenance chain to verbatim source quotes via `wiki_claim_provenance`. The wiki page remains the source of truth; this table is a materialized view backed by `*.beliefs.json` sidecars on disk.

```sql
CREATE TABLE wiki_beliefs (
  belief_id          TEXT PRIMARY KEY,
  workspace          TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,

  statement          TEXT NOT NULL,           -- ≤ 280 chars; one assertion per row
  topic              TEXT NOT NULL,

  subject            TEXT,                    -- optional structured fields (best-effort)
  predicate          TEXT,
  object             TEXT,

  wiki_document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  wiki_section_anchor TEXT,
  footnote_ids       TEXT NOT NULL,           -- JSON array
  provenance_ids     TEXT NOT NULL,           -- JSON array of wiki_claim_provenance.id

  asserted_at        TEXT NOT NULL,
  asserted_in_run    TEXT NOT NULL REFERENCES runs(run_id),
  superseded_at      TEXT,
  superseded_by_belief_id  TEXT REFERENCES wiki_beliefs(belief_id),
  superseded_in_run  TEXT REFERENCES runs(run_id),
  supersession_reason TEXT,                   -- 'contradicted_by_new_source'|'elaborated'|'manual_correction'|'source_drifted'

  source_valid_from  TEXT,                    -- when the source itself says the fact applies
  source_valid_to    TEXT,

  supporting_count   INTEGER NOT NULL DEFAULT 1,
  contradicting_belief_ids TEXT,              -- JSON array
  confidence_hint    TEXT,                    -- 'single_source'|'multi_source'|'authoritative'|'contested'

  created_at         TEXT NOT NULL,

  CHECK (supersession_reason IS NULL OR superseded_at IS NOT NULL),
  CHECK (length(statement) <= 280)
);

CREATE INDEX idx_beliefs_workspace_topic    ON wiki_beliefs(workspace, topic);
CREATE INDEX idx_beliefs_workspace_current  ON wiki_beliefs(workspace) WHERE superseded_at IS NULL;
CREATE INDEX idx_beliefs_subject_predicate  ON wiki_beliefs(workspace, subject, predicate) WHERE subject IS NOT NULL;
CREATE INDEX idx_beliefs_wiki_doc           ON wiki_beliefs(wiki_document_id);
CREATE INDEX idx_beliefs_asserted_at        ON wiki_beliefs(workspace, asserted_at DESC);
CREATE INDEX idx_beliefs_superseded_at      ON wiki_beliefs(workspace, superseded_at DESC) WHERE superseded_at IS NOT NULL;

CREATE VIRTUAL TABLE wiki_beliefs_fts USING fts5(
  statement, topic, subject, predicate, object,
  content='wiki_beliefs', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```

The `*.beliefs.json` sidecars sit next to wiki pages on disk:

```
wiki/topics/auth.md              ← canonical wiki page
wiki/topics/auth.beliefs.json    ← machine-readable belief extract (git-versioned)
```

`llmwiki reindex --rebuild-beliefs` walks `wiki/**/*.beliefs.json` and rebuilds `wiki_beliefs` deterministically. The sidecar is the source of truth; the SQLite table is the queryable index. Filesystem-first invariant honoured.

### `subscriptions_queue`
Pending subscription items not yet acted on. Used by the `subscriptions` MCP tool.

```sql
CREATE TABLE subscriptions_queue (
  document_id     TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  adapter_id      TEXT NOT NULL,
  received_at     TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'  -- 'pending'|'ingested'|'dismissed'
);
```

### `events` — the event-stream layer
Fine-grained activity from GitHub, Calendar, Gmail, Slack, Discord, cloud storage, etc. Unlike `documents`, events do **not** live as files on disk — they are too numerous, too small, and born from API calls rather than filesystem content. SQLite is the source of truth for events; digest files under `raw/timeline/<period>.md` are generated by the agent on demand.

See `10_event_streams.md` for the full design rationale, platform catalog, and adapter strategies.

```sql
CREATE TABLE events (
  id              TEXT PRIMARY KEY,                -- internal UUID
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  adapter_id      TEXT NOT NULL REFERENCES source_adapters(id) ON DELETE CASCADE,
  source          TEXT NOT NULL,                   -- 'github' | 'calendar' | 'slack' | 'gmail' | ...
  event_type      TEXT NOT NULL,                   -- 'push' | 'pr_opened' | 'message' | 'meeting' | ...
  external_id     TEXT NOT NULL,                   -- stable ID in the source
  occurred_at     TEXT NOT NULL,                   -- ISO timestamp, the "when" of the event
  ingested_at     TEXT NOT NULL,
  actor           TEXT,                            -- user/author handle
  subject         TEXT,                            -- one-line summary for display + search
  body            TEXT,                            -- full content where applicable
  refs            TEXT,                            -- JSON array of cross-stream IDs: ["#123", "abc1234", "msg-uuid"]
  payload         TEXT NOT NULL,                   -- JSON blob with source-specific fields
  UNIQUE(workspace, source, external_id)
);

CREATE INDEX idx_events_workspace_time ON events(workspace, occurred_at DESC);
CREATE INDEX idx_events_adapter_time   ON events(adapter_id, occurred_at DESC);
CREATE INDEX idx_events_actor          ON events(workspace, actor, occurred_at DESC);
CREATE INDEX idx_events_type           ON events(workspace, event_type, occurred_at DESC);

-- FTS over event subject + body so search crosses documents and events uniformly
CREATE VIRTUAL TABLE events_fts USING fts5(
  subject, body, refs,
  content='events', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```

**The `refs` column is the cross-stream correlation key.** When ingesting a Slack message, the adapter extracts anything that looks like `#123`, a commit SHA, a PR number, a Zoom link, or a meeting ID and stores them in `refs`. When the agent asks "what events relate to PR #123?" it's one `events(refs_contains="#123")` call or one `grep` over `events_fts`. No automated entity linker — the agent walks correlations at query time.

### `automations` (optional, post-MVP hook)
Opt-in rules like "auto-ingest Notion pages into workspace X."
```sql
CREATE TABLE automations (
  id              TEXT PRIMARY KEY,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  trigger         TEXT NOT NULL,           -- 'subscription'|'sync'|'cron'
  match           TEXT,                    -- JSON predicate
  action          TEXT NOT NULL,           -- 'ingest'|'lint'|'notify'
  enabled         INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL
);
```

## Path conventions inside a workspace

Mirrors `reference/03_astrohan_skill.md`:

- `raw/<adapter-type>/<...>` — raw layer. Organized by adapter to keep provenance visible.
- `wiki/overview.md` — hub page (mandatory).
- `wiki/index.md` — table of contents (mandatory).
- `wiki/log.md` — append-only log (mandatory).
- `wiki/<topic>/<concept|entity>.md` — one topic level only.
- `wiki/archives/<slug>.md` — immutable query snapshots.

Cross-references inside wiki pages use relative paths:
- Same topic: `other-article.md`
- Cross topic: `../other-topic/other-article.md`
- To raw: `../../raw/<adapter>/<file>.md`

## Markdown schema on wiki pages

Every concept/entity page has frontmatter + footnotes:

```markdown
# Title

> Sources: Author1, 2026-03-15; Author2, 2026-04-01
> Raw: [source1](../../raw/papers/paper1.pdf); [source2](../../raw/notion/notes.md)
> Updated: 2026-04-15

## Overview
One paragraph.

## Body
Synthesized content with citations[^1] and cross-links[^2].

[^1]: paper1.pdf, p.3
[^2]: notes.md
```

The `write` tool validates this on `create` — missing Sources line or zero footnotes on a body page is rejected. Structural pages (`overview`, `index`, `log`, archives) are exempt via an allowlist.

## Reindex semantics

`llmwiki reindex [--workspace X]`:

1. Walks the workspace(s) on disk.
2. For each file: compute sha256, compare to `documents.content_hash`. If different or missing, update/insert.
3. Rebuild `documents_fts`.
4. Re-parse every `wiki/log.md` into `wiki_log_entries`.
5. Re-parse every wiki page's footnotes into `wiki_claim_provenance`.
6. Flag orphaned rows (files that no longer exist on disk) as archived.

This is the disaster-recovery path and the migration path. Any schema change ships with a reindex-required version bump.

## Why not just use files without SQLite?

Three things the filesystem can't give us:

1. **Fast cross-cutting search.** Grep works for `<200` files. Past that, FTS5 wins by orders of magnitude.
2. **Structured history.** Parsing `log.md` on every `history()` call is wasteful; an indexed table isn't.
3. **Provenance joins.** "Which wiki pages cite this raw file?" is a one-line SQL query against `wiki_claim_provenance`. Without SQLite, it's a grep-every-wiki-page scan.

SQLite is the cheapest possible answer to those needs and nothing more. It never holds state that isn't derivable from the files.
