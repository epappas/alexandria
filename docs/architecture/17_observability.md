# 17 — Observability

> **Cites:** `research/reviews/02_mlops_engineer.md` (#10, recommendations on run_id correlation + `llmwiki status --json`), `13_hostile_verifier.md` (the runs table is the observability backbone).

## Principles

1. **Local, structured, correlatable.** Every event lands as a line in a local JSONL file with a `run_id` field. No cloud service, no telemetry, no Prometheus scrape unless the user explicitly asks for it.
2. **Actionable.** Every observable signal must answer *"what do I do next?"*. Raw stats without guidance are noise.
3. **Read-only by design.** Observability tools never write to `wiki/`. They read the runs table, read the log files, format, and return.
4. **One run_id spans the whole causality chain.** A user invokes `ingest`; the parent assigns a run_id; the scheduler logs it; the adapter logs it; the LLM provider logs it; the verifier logs it; the git commit records it; `wiki/log.md` references it. One ID, one story.

## The log families

All under `~/.llmwiki/logs/`, rotated daily:

| File | Source | Contents |
|---|---|---|
| `daemon-YYYY-MM-DD.jsonl` | Parent process supervisor | Lifecycle events, child starts/kills, schema migration results, FTS verification, orphaned-run sweeps |
| `sync-YYYY-MM-DD.jsonl` | Source and subscription adapters | Adapter runs: start, items fetched, rate-limit stalls, circuit-breaker state changes, errors |
| `mcp-YYYY-MM-DD.jsonl` | MCP server (stdio and HTTP) | Tool calls: tool name, workspace, args hash (no values), latency, result size, errors |
| `llm-usage-YYYY-MM-DD.jsonl` | LLM provider wrappers | Completions: preset, model, tokens in/out, cache read/write, USD, latency, stop reason |
| `verifier-YYYY-MM-DD.jsonl` | Hostile verifier runs | Verdict, per-claim findings, findings by category, tokens used, time to verdict |
| `eval-YYYY-MM-DD.jsonl` | Evaluation scaffold | Metric runs: M1-M5 scores, sample sizes, trend signals, threshold breaches |
| `hook-YYYY-MM-DD.jsonl` | Conversation-capture hooks | Hook invocations, mined session IDs, skipped sessions, errors |

### Common line shape

```json
{
  "ts": "2026-04-16T14:23:45.012Z",
  "run_id": "2026-04-16-abc123",
  "workspace": "research",
  "layer": "llm-usage",
  "event": "completion",
  "level": "info",
  "correlation": {
    "parent_run": null,
    "trace_id": "2026-04-16-abc123"
  },
  "data": {
    "preset": "claude-sonnet",
    "model": "claude-sonnet-4-6",
    "tokens_in": 3421,
    "tokens_out": 812,
    "cache_read": 3200,
    "cache_write": 0,
    "usd": 0.018,
    "latency_ms": 4271,
    "stop_reason": "end_turn"
  }
}
```

Required fields on **every** line:
- `ts` — ISO 8601 with millisecond precision.
- `run_id` — from the runs table in `13_hostile_verifier.md`, OR the daemon's per-boot session id if no run exists.
- `workspace` — slug, or `__global__` for daemon-level events.
- `layer` — which log family this line belongs to (denormalized for grep).
- `event` — short identifier.
- `level` — `debug`|`info`|`warn`|`error`|`crash`.
- `data` — arbitrary per-event payload.

Optional:
- `correlation.parent_run` — when a child run was spawned by another run (e.g., verifier by ingest).
- `correlation.trace_id` — usually equal to run_id but can span multiple runs for an end-to-end user action.

## `run_id` correlation — the story

When a user runs `llmwiki ingest paper.pdf`:

1. The CLI generates `run_id = 2026-04-16-<uuid7>` and passes it to the daemon via the IPC socket.
2. The daemon records a `runs` row (`status='pending'`, `run_type='ingest'`).
3. The daemon writes to `daemon-*.jsonl`: `{run_id, event='run_started', data={...}}`.
4. The daemon spawns the guardian loop with the run_id bound in context.
5. The guardian reads the source (logs to `mcp-*.jsonl`), calls the LLM (logs to `llm-usage-*.jsonl`), stages writes to `runs/<run_id>/staged/`, and passes the run to the verifier.
6. The verifier is a sub-run with `parent_run = <run_id>` and its own `run_id`. It logs to `verifier-*.jsonl`.
7. On commit, the daemon logs to `daemon-*.jsonl`: `{run_id, event='run_committed'}`.
8. The git commit carries `run_id` in its message footer: `llmwiki: run 2026-04-16-abc123`.
9. `wiki/log.md` records `## [2026-04-16] ingest | paper.pdf (run 2026-04-16-abc123)`.
10. `wiki_log_entries` records the same run_id.

**`llmwiki logs show <run_id>`** merges all log-family entries with matching `run_id` OR matching `correlation.parent_run` into a single timestamp-sorted stream:

```
$ llmwiki logs show 2026-04-16-abc123

2026-04-16T14:20:00.000Z  daemon       run_started           research       ingest paper.pdf
2026-04-16T14:20:00.142Z  mcp          tool_call             research       read(path=raw/papers/paper.pdf)
2026-04-16T14:20:00.891Z  llm-usage    completion            research       claude-opus 14k→2.8k tokens $0.12
2026-04-16T14:20:05.234Z  mcp          tool_call             research       write(create,...)
2026-04-16T14:20:08.501Z  daemon       run_staged            research       7 files staged
2026-04-16T14:20:08.601Z  verifier     verifier_started      research       [child run 2026-04-16-abc123/v1]
2026-04-16T14:20:12.412Z  llm-usage    completion            research       claude-sonnet 18k→1.2k tokens $0.02
2026-04-16T14:20:12.501Z  verifier     verdict               research       commit (per-claim findings: 12 supports, 0 weak)
2026-04-16T14:20:12.800Z  daemon       run_committed         research       git: c0ffee1
2026-04-16T14:20:12.850Z  daemon       wiki_log_appended     research       log.md updated
```

This is the post-mortem tool. A user asks *"what happened in last night's scheduled run?"* and a single command tells the whole story in order.

## `llmwiki status --json`

The single-call operational dashboard. Returns a JSON blob covering:

```json
{
  "daemon": {
    "pid": 12834,
    "uptime_sec": 482391,
    "state": "running",
    "children": {
      "scheduler":       {"pid": 12835, "state": "running", "last_beat": "2026-04-16T14:23:41Z"},
      "adapter_workers": {"pool": 4, "active": 2, "dead": 0},
      "synthesis_worker":{"pid": 12840, "state": "idle",    "last_beat": "2026-04-16T14:23:40Z"},
      "mcp_http":        {"pid": 12841, "state": "running", "connections": 1},
      "webhook_recv":    {"pid": 12842, "state": "running"},
      "web_ui":          {"pid": 12843, "state": "running"}
    }
  },
  "database": {
    "schema_version": 7,
    "sqlite_size_bytes": 48293721,
    "wal_size_bytes": 1048576,
    "fts_integrity": "ok",
    "last_backup_at": "2026-04-15T03:00:00Z",
    "last_backup_age_hours": 35.4
  },
  "workspaces": [
    {
      "slug": "research",
      "wiki_pages": 94,
      "raw_sources": 123,
      "events_last_7d": 412,
      "pending_subscriptions": 6,
      "last_ingest_at": "2026-04-16T13:15:00Z",
      "last_synthesis_at": "2026-04-14T03:00:00Z",
      "synthesis_paused": false,
      "drafts_awaiting_review": 0,
      "eval": {
        "M1": {"score": 0.97, "status": "healthy",  "last_run": "2026-04-14T03:30:00Z"},
        "M2": {"score": 0.93, "status": "healthy",  "last_run": "2026-04-16T13:20:00Z"},
        "M3": {"score": 0.84, "status": "healthy",  "last_run": "2026-04-01T04:00:00Z"},
        "M4": {"crossover_week": 19,                 "last_run": "2026-04-16T14:00:00Z"},
        "M5": {"score": 0.96, "status": "healthy",  "last_run": "2026-04-14T04:30:00Z"}
      }
    }
  ],
  "adapters": [
    {
      "id": "gh-acme-web",
      "type": "github",
      "workspace": "research",
      "circuit_breaker": "closed",
      "last_run_at": "2026-04-16T14:20:00Z",
      "last_run_status": "success",
      "next_run_at": "2026-04-16T14:25:00Z",
      "items_last_run": 12
    },
    {
      "id": "slack-research",
      "type": "slack",
      "workspace": "research",
      "circuit_breaker": "open",
      "opened_at": "2026-04-16T13:45:00Z",
      "cooldown_until": "2026-04-16T14:50:00Z",
      "last_error": "429 Too Many Requests"
    }
  ],
  "rate_limits": {
    "github":    {"capacity": 5000, "available": 4823, "refill_per_sec": 1.389},
    "slack":     {"capacity": 50,   "available": 0,    "refill_per_sec": 1}
  },
  "budgets": {
    "research": {
      "scheduled_synthesis_monthly_usd_used": 4.28,
      "scheduled_synthesis_monthly_usd_cap":  20.00,
      "scheduled_synthesis_runs_this_month":  2
    }
  },
  "warnings": [
    "slack-research adapter circuit breaker open until 14:50 UTC",
    "last backup is 35h old — consider running llmwiki backup create"
  ]
}
```

The `warnings` array is the **actionable** subset. If this array is empty, the system is healthy; if non-empty, the user reads it and acts.

### CLI formats

```
llmwiki status               # pretty-printed human output
llmwiki status --json        # the blob above
llmwiki status --workspace X # scoped to one workspace
llmwiki status --watch       # refresh every 5s (curses-ish)
```

## Crash dumps

On an unhandled exception anywhere in the daemon:

1. A traceback is written to `~/.llmwiki/crashes/<timestamp>-<pid>-<child>.txt`.
2. A state snapshot is appended: recent tool calls from the crashed run (if any), last heartbeats, current rate-limiter state, open file handles.
3. The parent supervisor logs `{event='child_crashed', child=<name>, pid=<pid>, dump_path=<path>}` to `daemon-*.jsonl`.
4. The crash count is surfaced in `llmwiki status` as a warning.

Python `faulthandler` is enabled at import time for every child, which catches segfaults from C extensions (FTS5, asyncpg bindings) and writes a stack trace to stderr. The parent supervisor captures child stderr and routes to the crash dump file.

### `llmwiki doctor`

```
llmwiki doctor [--workspace X]
```

Runs a suite of checks and reports pass/fail with actionable remediation:

```
[OK]   SQLite database is readable
[OK]   Schema version 7 matches binary expectation
[OK]   FTS5 integrity verified
[OK]   All workspace directories present
[OK]   Keyring secret store accessible
[WARN] No backup in the last 24 hours
       → run: llmwiki backup create
[OK]   MCP stdio entry point is executable
[OK]   Claude Code hook installed and verified
[ERR]  slack-research adapter circuit breaker open
       → investigate: cat ~/.llmwiki/logs/sync-2026-04-16.jsonl | jq 'select(.data.adapter_id == "slack-research")'
[WARN] No scheduled synthesis in the last 14 days
       → check: llmwiki synthesize review
[OK]   Eval M1 healthy on all workspaces
[OK]   Eval M2 healthy on all workspaces
```

Doctor is the first thing a user runs when *"something feels off"*. It points at specific log lines, specific commands, specific fixes. No generic advice.

## Tracing the verifier's work specifically

Because the hostile verifier is the load-bearing correctness mechanism, its runs are observable in two places:

1. **`verifier-*.jsonl`** — every verdict with per-claim findings.
2. **`llmwiki runs show <run_id>`** — the cross-log unified view with the verifier as a sub-run.

A user who wants to understand *"why did the verifier reject this ingest?"* runs:

```
llmwiki runs show 2026-04-16-abc123
```

And sees every step from read-source → stage → verify → reject, with the reject reason and the per-claim findings inlined. This is the debug surface for correctness issues.

## No telemetry, no opt-out required

Everything in this doc writes to local files under `~/.llmwiki/`. There is no network traffic, no phone-home, no anonymized metrics server, no crash reporter uploading to an issue tracker. The observability surface is fully inspectable by the user with `jq`, `grep`, and a text editor. This is non-negotiable — it follows directly from invariant #1 (single-user, local).

Users who want remote observability can run their own OpenTelemetry collector against the JSONL files. llmwiki does not ship it, and the architecture assumes it does not exist.

## SOLID application

- **Single Responsibility.** Each log family is a separate file with a separate emitter. One log family, one purpose. Downstream tools that want to merge read from all of them via `run_id`.
- **Open/Closed.** Adding a new log family is adding a file path to the emitter registry. No changes to `llmwiki logs show`.
- **Liskov.** Every log line has the common shape above. Code that parses one line parses them all.
- **Interface Segregation.** The status command reads from the runs table, the heartbeats table, and the last N log lines. It does not couple to the adapter implementations or the LLM provider internals.
- **Dependency Inversion.** The status blob is produced by a `StatusReporter` class that composes `DaemonInspector`, `DbInspector`, `WorkspaceInspector`, and `AdapterInspector`. Each inspector is a narrow interface; tests substitute fakes.

## DRY notes

- **One run_id** threaded through every log family eliminates the need for separate correlation systems.
- **One line shape** means one parser.
- **One `status` command** aggregates what would otherwise be a dozen separate `list-*` commands.
- **One doctor** centralizes every "is my install healthy" check instead of scattering them across per-component scripts.

## KISS notes

- Logs are JSONL. Readable with `tail -f | jq`. No Parquet, no Avro, no binary format.
- Status is one JSON document. No Prometheus, no Grafana, no push gateway.
- Doctor is a sequence of checks with pass/fail/warn and one remediation line each. No dependency graph.
- Crash dumps are text files. Read them with `cat`.

## What this doc does NOT cover

- **The runs and source_runs tables** — defined in `13_hostile_verifier.md` and `06_data_model.md`.
- **What each log family's event types mean semantically** — a reference doc that I will build as the emitter registry grows. For now, the JSONL is self-describing.
- **Daemon supervision logic itself** — `16_operations_and_reliability.md`.
- **Secrets redaction in logs** — `18_secrets_and_hooks.md`.
- **Evaluation metric scoring** — `14_evaluation_scaffold.md`.

## Summary

Seven log families, one `run_id` field correlating everything, one `llmwiki status --json` surfacing operational state, one `llmwiki logs show <run_id>` for post-mortem tracing, one `llmwiki doctor` for health checks, one `llmwiki runs show` for verifier debugging. Crash dumps go to `~/.llmwiki/crashes/`. No telemetry. No cloud.

Every observable question the user will ask has exactly one command that answers it.
