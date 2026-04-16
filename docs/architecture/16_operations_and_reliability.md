# 16 — Operations and Reliability

> **Cites:** `research/reviews/02_mlops_engineer.md` (#1, #2, #3, #4, #5, #9, all recommendations), `research/reviews/01_llm_architect.md` (§2.7 concurrent writer).

## Scope

This doc covers the **operational infrastructure** that keeps alexandria trustworthy in production: daemon supervision, schema migrations, source-run state machines, rate limiting, circuit breakers, backup/restore, and FTS5 integrity. The *observability* for these systems lives in `17_observability.md`. The *secrets management* and *hook lifecycle* live in `18_secrets_and_hooks.md`.

Every concern in this doc maps to a specific mlops-engineer critique or recommendation. DRY: each concern has exactly one home.

## 1. Daemon supervision — supervised subprocesses, not threads

**Closes:** mlops #4, recommendation on splitting the daemon.

The current `02_system_architecture.md` describes one `alexandria daemon` process doing scheduler, pollers, ingestion workers, webhook receivers, MCP HTTP server, and the web UI. A crash anywhere takes the whole thing down. The fix is a **supervised-subprocess model** with a thin parent process owning lifecycle and IPC.

### Process topology

```
alexandria daemon (parent)
├── scheduler          (apscheduler loop; picks the next job)
├── adapter_workers    (pool of K processes; one job each)
├── synthesis_worker   (isolated; scheduled temporal synthesis only)
├── mcp_http           (fastmcp HTTP+SSE server; stateless)
├── webhook_recv       (HTTP listener for push webhooks)
└── web_ui             (read-only dashboard server)
```

Each child is a separate OS process (not a thread, not an asyncio task — a `multiprocessing.Process` or equivalent). The parent owns:

1. The SQLite connection pool.
2. The child lifecycle (start, health-check, restart, kill).
3. The IPC channel (Unix domain socket, JSON protocol).
4. The shared logger (see `17_observability.md`).

Children request scoped DB sessions from the parent via the IPC socket. They do not open their own SQLite handles. This avoids SQLite multi-writer contention and keeps the connection pool audit-able.

### Restart policy per child

| Child | Policy | Rationale |
|---|---|---|
| `scheduler` | `Restart=always`, exponential backoff 1s → 300s cap | Scheduler loss is total loss of automation. |
| `adapter_workers` | Per-worker `Restart=on-failure`, max 5 restarts in 60s → quarantine | A single adapter's bug should not starve the pool. |
| `synthesis_worker` | `Restart=manual` if killed mid-run | Runs are expensive; a crash needs human triage (see `runs` table from `13_hostile_verifier.md`). |
| `mcp_http` | `Restart=always` | MCP clients need a stable endpoint. |
| `webhook_recv` | `Restart=always` | Missed webhooks are re-delivered by the upstream provider on retry. |
| `web_ui` | `Restart=on-failure` | Read-only; cheap to lose. |

### Liveness and heartbeat

Every child writes a heartbeat row to SQLite every 5 seconds:

```sql
CREATE TABLE daemon_heartbeats (
  child_name   TEXT PRIMARY KEY,
  pid          INTEGER NOT NULL,
  started_at   TEXT NOT NULL,
  last_beat    TEXT NOT NULL,
  state        TEXT NOT NULL  -- 'starting'|'running'|'draining'|'failed'
);
```

The parent scans this table every 15 seconds. Any child missing 3 consecutive heartbeats (45 seconds) is considered dead — the parent kills the PID (`SIGKILL` if `SIGTERM` ignored) and applies the restart policy.

Heartbeat updates are unrelated to the operational work of the child; a blocked adapter call does not stop the process from emitting a heartbeat, so "blocked on I/O" is distinguishable from "crashed." If a child is genuinely blocked (heartbeat updates but no forward progress on its job queue), a separate **stall detector** in the scheduler flags it.

### Orphaned-run cleanup on startup

**Closes:** mlops #4 — source_runs state machine.

On every parent-process startup (cold start or restart), the parent runs a **sweep**:

```sql
-- Runs table from 13_hostile_verifier.md
UPDATE runs
   SET status = 'abandoned',
       ended_at = now(),
       reject_reason = 'daemon restart'
 WHERE status IN ('pending','verifying');

-- Source runs table from 06_data_model.md
UPDATE source_runs
   SET status = 'abandoned',
       finished_at = now(),
       error = 'daemon restart'
 WHERE status = 'running';

-- Daemon heartbeats table
DELETE FROM daemon_heartbeats;
```

The sweep runs inside a single transaction. After the sweep, the parent starts its children. No child ever sees a stale `running` state. The sweep is idempotent: re-running it on an already-clean database is a no-op.

For synthesis runs specifically, the sweep additionally moves `runs/<run_id>/staged/` to `runs/<run_id>/failed/` so the filesystem state matches the SQLite state. Staged runs that crash mid-verify are not resumed — the user sees them in `alexandria synthesize review` and decides whether to retry.

### Concurrent writers on the same workspace — the llm-architect §2.7 question

Two MCP clients bind the same workspace and both try to `write` at once:

1. **SQLite writes are serialized by WAL mode.** Two simultaneous writes get one immediate execution and one brief blocking wait; neither corrupts anything.
2. **Filesystem writes are serialized by a per-workspace file lock.** The guardian acquires `~/.alexandria/workspaces/<slug>/.lock` (an `fcntl` advisory lock) before staging any run. Second writer waits up to 30 seconds; past that, the MCP tool returns `workspace_busy` and the caller decides whether to retry.
3. **Cross-session deduplication via session_id.** When the conversation-capture adapter (`12_conversation_capture.md`) processes two transcripts from the same session simultaneously (e.g., after a restart), the `session_lock` table enforces serial processing per `session_id`.

First writer wins, second waits or fails loud. No silent races. The invariant is: **every commit to `wiki/` happens inside a file-locked run**, and the lock release and the git commit are the last two steps of the commit transaction.

## 2. Schema migrations framework

**Closes:** mlops #3, recommendation on `alexandria db migrate`.

### The `schema_migrations` table

```sql
CREATE TABLE schema_migrations (
  version      INTEGER PRIMARY KEY,
  name         TEXT NOT NULL,
  script_path  TEXT NOT NULL,
  script_sha256 TEXT NOT NULL,
  applied_at   TEXT NOT NULL,
  applied_by   TEXT NOT NULL  -- 'auto-on-startup'|'cli'|'manual'
);

-- Source of truth for current version
INSERT INTO schema_migrations (version, name, script_path, script_sha256, applied_at, applied_by)
VALUES (0, 'bootstrap', 'builtin', '', '2026-01-01T00:00:00Z', 'builtin');
```

`PRAGMA user_version` mirrors `MAX(version) FROM schema_migrations` and is set at the end of every successful migration. Tools that need a cheap version check read the pragma; tools that need full history read the table.

### Migration files

```
alexandria/migrations/
├── 0001_initial.sql
├── 0002_add_events.sql
├── 0003_add_runs_and_verifier.sql
├── 0004_add_eval_tables.sql
├── 0005_add_wiki_claim_quote_anchors.sql
├── 0006_add_schema_migrations.sql
├── 0007_add_daemon_heartbeats.sql
└── ...
```

Files are **ordered, immutable, and checksummed**. A migration file that has been applied (its sha256 is in the table) and then edited later will fail the daemon startup check with a `migration tampered` error. The only way to fix a broken migration is to write a new one that corrects the damage.

### `alexandria db migrate`

```
alexandria db migrate                    # apply all pending migrations
alexandria db migrate --target 0005      # apply through version 5 only
alexandria db migrate --dry-run          # show what would run
alexandria db status                     # current version + pending list
alexandria db downgrade --target <v>     # not supported — returns an error pointing to backup/restore
```

**Workflow:**

1. `alexandria db migrate` opens the SQLite file.
2. Reads `MAX(version) FROM schema_migrations` — call it `current`.
3. Scans `alexandria/migrations/` for files with version > `current`, sorted ascending.
4. For each pending migration:
   - **Take a named backup** to `~/.alexandria/db/backups/pre-migration-YYYYMMDD-HHMMSS-v<N>.db` via `sqlite3_backup_init` (not file copy — WAL-safe).
   - Compute the script sha256.
   - Execute the script inside a `BEGIN IMMEDIATE` transaction.
   - Insert the `schema_migrations` row.
   - Set `PRAGMA user_version`.
   - Commit.
5. If any step fails, the transaction rolls back. The backup is preserved. The user is told which file failed and at what statement.

### Auto-migration on daemon startup

By default, the parent process runs `alexandria db migrate` before starting any children. The user can opt out with `[daemon] auto_migrate = false` in `config.toml`, which causes the daemon to refuse to start on a version mismatch and require an explicit `alexandria db migrate` run.

### Downgrade policy

**Downgrade is not supported in-place.** Rolling back a schema change on a live SQLite database with application data is a landmine. Instead, the user:

1. Stops the daemon.
2. Restores the backup from `~/.alexandria/db/backups/`.
3. Installs the older binary version.
4. Starts the daemon.

This is documented explicitly in `alexandria db status` output when the current schema version is ahead of the installed binary's expected version.

## 3. Rate limiter and circuit breakers

**Closes:** mlops #5, recommendation on per-provider rate limiting.

### Per-provider token-bucket rate limiter

One `RateLimiter` instance per daemon, with a bucket per provider:

```python
class RateLimiter:
    def __init__(self, buckets: dict[str, TokenBucket]): ...
    async def acquire(self, provider: str, cost: int = 1) -> None: ...
    def status(self) -> dict[str, BucketStatus]: ...


class TokenBucket:
    capacity: int
    fill_rate: float   # tokens per second
    tokens: float
    last_refill: float
    def try_acquire(self, cost: int) -> bool: ...
    async def acquire(self, cost: int) -> None: ...
```

Buckets are configured from the adapter's documented limits:

```toml
[rate_limits]
github     = { capacity = 5000, fill_rate_per_sec = 1.389 }   # 5000/hr
gmail      = { capacity = 250,  fill_rate_per_sec = 2.5 }      # 250/user/sec
slack      = { capacity = 50,   fill_rate_per_sec = 1 }        # tier-dependent; conservative default
discord    = { capacity = 50,   fill_rate_per_sec = 1 }
notion     = { capacity = 100,  fill_rate_per_sec = 3 }
anthropic  = { capacity = 50,   fill_rate_per_sec = 1 }        # for daemon-owned LLM calls
openai     = { capacity = 100,  fill_rate_per_sec = 2 }
```

Every adapter and every LLM provider call goes through `rate_limiter.acquire(provider, cost)` before the actual HTTP call. Starvation is prevented with FIFO queuing per bucket.

### Per-adapter circuit breaker

Each adapter instance has its own circuit breaker wrapping its `fetch` call:

```python
class CircuitBreaker:
    state: Literal["closed", "open", "half_open"]
    failure_count: int
    opened_at: float | None
    # On failure: increment, if threshold reached → open
    # When open: reject immediately until cooldown elapsed
    # After cooldown: enter half_open, next call probes
    # On half_open success → closed; on failure → open with fresh cooldown
```

Configuration:

```toml
[circuit_breakers.default]
failure_threshold       = 5
cooldown_seconds        = 300
half_open_probe_timeout = 30
```

Failure definition per adapter:

- HTTP 429 / 529 — always a failure, always opens (no threshold).
- HTTP 5xx — counts toward threshold.
- Timeout — counts toward threshold.
- HTTP 401 / 403 — not a rate issue; marks adapter `auth_required`, not `failed`. Opens the breaker but also raises an alert.

### Visible status

Both rate limiter and circuit breakers expose their state via `alexandria status` (see `17_observability.md`). A user who sees *"GitHub rate-limited, retry in 00:14:22"* knows exactly what is happening.

### No waiting forever

If a caller blocks on `rate_limiter.acquire` for more than 60 seconds, the call is cancelled and the adapter logs a `RateLimitStallError`. The job is not retried immediately — it is re-scheduled for the next normal cadence. This prevents a thundering-herd retry storm after a long rate-limit window.

## 4. Backup and restore

**Closes:** mlops recommendation on `alexandria backup create|restore`, mlops #1 on event-layer backup.

### `alexandria backup create`

```
alexandria backup create [--output <path>] [--workspace <slug>] [--include-secrets]
```

Produces a timestamped tar.gz containing:

```
alexandria-backup-<timestamp>/
├── manifest.json           # version, checksum, creation time
├── db/
│   └── alexandria.sqlite       # via sqlite3 .backup — WAL-safe, consistent snapshot
├── workspaces/
│   └── <slug>/
│       ├── raw/              # direct copy
│       ├── wiki/             # via git bundle — preserves history
│       └── config.toml
├── secrets/                  # only if --include-secrets; still encrypted
│   └── *.enc
├── logs/                     # recent logs (last 30 days)
│   └── *.jsonl
└── state/
    └── hook_state/           # hook state dirs
```

The SQLite snapshot uses `sqlite3_backup_init` (API call, not file copy) to get a consistent point-in-time view while the daemon may still be running. Git bundles preserve the full wiki history.

Secrets are **excluded by default** — restoring a backup on a new machine won't decrypt them anyway because the OS-keyring-derived key differs. Users with `passphrase` mode (see `18_secrets_and_hooks.md`) can include secrets with `--include-secrets` and re-enter the passphrase on restore.

### `alexandria backup restore`

```
alexandria backup restore <archive-path> [--into <dir>] [--dry-run]
```

- Refuses to run over a non-empty `~/.alexandria/` unless `--into` points to a different directory.
- Verifies the manifest checksum before unpacking.
- Unpacks workspaces, runs `alexandria db migrate` against the restored SQLite to bring it to the current binary's schema version, and re-runs `alexandria reindex --fts-rebuild` to re-construct FTS indexes.
- Does NOT re-fetch events from source APIs. Events in the backup are all you get. The restore docs say so plainly.

### What the backup does NOT protect against

**Event-layer retention at the source** (mlops #1). If your SQLite is lost AND your latest backup is older than 30 days, your GitHub events older than 30 days are permanently gone — the GitHub Events API cap (verified in `research/raw/33_github_events_api.md`) cannot recover them. The same applies to Slack free tier (90-day access), Gmail history (7-day sliding window), and similar sources.

The backup is your **actual** event-layer backup window. Users who care about event history run `alexandria backup create` on a cron — typically daily:

```cron
0 3 * * * /usr/local/bin/alexandria backup create --output /backup/alexandria-$(date +\%Y\%m\%d).tar.gz
```

The `alexandria status` output surfaces *"last backup: N days ago"* so the user notices drift.

## 5. FTS5 integrity verification

**Closes:** mlops #2 on FTS5 fragility, mlops recommendation on `--fts-verify`.

### The fragility

`documents_fts` and `events_fts` are external-content FTS5 tables keyed by the source rowid. They stay in sync via triggers on INSERT/UPDATE/DELETE. Known failure modes:

1. Trigger fires, content table commit succeeds, FTS index write fails (WAL replay edge case).
2. External process modifies `documents` directly (tooling bug) without going through triggers.
3. `VACUUM` on a corrupted DB leaves FTS index references dangling.
4. A restored backup's FTS indexes were built against an older content-table rowid assignment that changed on restore.

Any of these produce silent result corruption — searches return wrong or missing rows with no error.

### `alexandria reindex --fts-verify`

```python
def fts_verify() -> FtsVerifyReport:
    content_count = sql("SELECT COUNT(*) FROM documents")
    fts_count = sql("SELECT COUNT(*) FROM documents_fts")
    if content_count != fts_count:
        return FtsVerifyReport(status='mismatch',
                               content=content_count, fts=fts_count)
    # Spot-check 100 random rowids for FTS retrievability
    sample = sql("SELECT rowid FROM documents ORDER BY RANDOM() LIMIT 100")
    for rowid in sample:
        if not sql("SELECT 1 FROM documents_fts WHERE rowid = ? LIMIT 1", rowid):
            return FtsVerifyReport(status='incomplete_fts', missing_rowid=rowid)
    return FtsVerifyReport(status='ok', rows=content_count)
```

### `alexandria reindex --fts-rebuild`

Runs `INSERT INTO documents_fts(documents_fts) VALUES('rebuild')` — the built-in FTS5 rebuild command — which is O(N) but correct. Works for both `documents_fts` and `events_fts`.

### Daemon-start integrity check

On every parent-process startup, after migrations but before starting children, the parent runs `fts_verify()`. If the result is `mismatch` or `incomplete_fts`:

1. Write a warning to `daemon-YYYY-MM-DD.jsonl`.
2. Mark FTS as `degraded` in `alexandria status`.
3. Start children anyway (FTS is for search; search still functions degraded).
4. Schedule a background `fts_rebuild` via the scheduler, single-threaded, low priority.
5. On rebuild completion, clear the `degraded` flag and log success.

The user sees the degradation in `alexandria status` and knows a rebuild is in flight. They can query the wiki during rebuild; search will be slow and incomplete until rebuild completes.

## 6. Kill switches for synthesis

**Closes:** mlops #9 on kill switches.

### `alexandria synthesize pause|resume`

```
alexandria synthesize pause [--workspace <slug>]    # creates ~/.alexandria/.disable-synthesis[-<slug>]
alexandria synthesize resume [--workspace <slug>]   # removes the sentinel
```

The scheduler checks for the sentinel file **before every synthesis run**, not just at daemon start. A paused synthesis survives daemon restart, survives schema migrations, survives reboot. The only way to resume is an explicit resume command (or deleting the file manually).

### `alexandria synthesize rollback <run_id>`

Reverts a committed synthesis run:

1. Look up the run in the `runs` table.
2. Revert the git commit that committed the run's wiki changes (`git revert <commit-sha>`).
3. Mark the run as `rolled_back` in the runs table.
4. Flag any downstream runs that depended on the rolled-back state as `depends_on_rolled_back` — these may need re-verification.
5. Log the rollback to `wiki/log.md` and append an entry to the run's verifier transcript.

Rollback is a write operation — it goes through the same staged-write mechanism as any other write. The "rollback" is itself a run with `run_type = 'rollback'`.

### `alexandria synthesize review`

Lists synthesis runs in states `pending`, `verifying`, `rejected`, or `committed` (last 30 days), with:

- run_id, timestamp, workspace, trigger
- verdict + reject reason (if any)
- pages touched
- user action needed

The user can `alexandria synthesize review <run_id>` for full details, or `alexandria synthesize accept|reject|retry <run_id>` for action.

## SOLID application

- **Single Responsibility.** This doc covers exactly six operational concerns. Each has a section, a schema (if applicable), and a set of CLI commands. No bleed into observability or secrets.
- **Open/Closed.** Adding a new child process to the daemon is adding a row to the policy table. Adding a new migration is adding a file. Adding a new adapter's rate limit is a config entry. No code changes to infrastructure.
- **Liskov.** All children conform to the same lifecycle interface: `start(config) → run() → drain() → stop()`. The parent treats them uniformly.
- **Interface Segregation.** The rate limiter exposes `acquire(provider, cost)` and `status()`. Nothing else. Circuit breakers expose `call(callable)` and `state()`. Nothing else.
- **Dependency Inversion.** The scheduler depends on a `JobRunner` interface, not on specific job types. Migrations depend on an abstract `Migrator` that could write to Postgres in a hypothetical v2 backend.

## DRY notes

- **One backup command** covers SQLite, filesystem, git history, config, and optionally secrets.
- **One migration framework** serves the whole schema; there is no per-table migration story.
- **One rate limiter instance** serves all adapters and all LLM providers.
- **One kill switch pattern** (sentinel files) is reused for any future automation the daemon owns.
- **One run-state sweep** in the parent handles both runs and source_runs tables.

## KISS notes

- The daemon is a parent + children; children are OS processes; communication is a local socket. No Kubernetes, no Docker, no systemd-nspawn.
- Migrations are numbered SQL files. No ORM migration framework.
- Rate limits are token buckets. No adaptive algorithms.
- Circuit breakers are three-state finite state machines. No exponential decay, no rolling windows.
- Backup is tar.gz. Restore is untar + reindex.

## What this doc does NOT cover

- **Log correlation, `alexandria status --json`, crash dumps, `alexandria doctor`** — `17_observability.md`.
- **Secrets management, hook install/uninstall, concurrent session locks** — `18_secrets_and_hooks.md`.
- **The runs table and verifier state machine** — `13_hostile_verifier.md`.
- **Evaluation metrics and the freeze clause** — `14_evaluation_scaffold.md`.
- **Cascade workflow and convergence policy** — `15_cascade_and_convergence.md`.

## Summary

The daemon is a supervised-subprocess architecture with per-child restart policy. Schema migrations are ordered immutable SQL files with auto-backup before each apply. Source runs are swept on startup so no `running` state persists across restart. Rate limits are per-provider token buckets; adapter failures open circuit breakers. Backup is a tar.gz of SQLite + filesystem + git bundle; restore unpacks + migrates + rebuilds FTS. FTS5 integrity is verified on every daemon start and can be rebuilt on demand. Synthesis has pause, resume, rollback, and review commands with a sentinel-file kill switch.

Every mlops concern about reliability is named, mechanized, and has a CLI entry point.
