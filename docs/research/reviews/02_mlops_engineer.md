# Review: MLOps Engineer

**Reviewer:** mlops-engineer specialist agent
**Date:** 2026-04-16
**Scope:** Full architecture + research folder, with focus on operations, reliability, deployment, schema evolution, observability, and failure modes.

**Note on fabrications:** The reviewer cites `08_config_and_secrets.md` which does not exist — our numbered doc at position 08 is `08_mcp_integration.md`, and secrets details live scattered across `06_data_model.md` and `11_inference_endpoint.md`. The reviewer flagged this as "by inference from references across the docs" — treat the critique as a real gap (we have no dedicated secrets doc) rather than a citation of existing content.

---

## Executive Take

The architecture is operationally thoughtful for a local-first single-user system and demonstrates unusual maturity in three places: the files-first invariant with `reindex` as the recovery escape hatch (`06_data_model.md:21-58`), the honest documentation of upstream retention limits per adapter (GitHub 30d, Slack 90d, Gmail 7d history windows — `10_event_streams.md:21-147`), and the draft-until-confirmed temporal synthesis model with per-run and monthly budget caps (`10_event_streams.md:531-619`, `11_inference_endpoint.md:98-181`). The provider-pluggable inference layer with cost telemetry to `llm-usage.jsonl` and the decision to keep stdio MCP working without the daemon are both operationally correct choices that preserve a minimum viable mode when everything else fails.

The biggest operational concern is **failure isolation inside the daemon**. `02_system_architecture.md:72-130` describes one `llmwiki daemon` process running scheduler, pollers, ingestion workers, webhook receivers, MCP HTTP server, and the web UI, all sharing the same process and a single SQLite database. A crash in the scheduled temporal synthesis agent loop, a memory leak in a source adapter, a file descriptor leak in the webhook receiver, or a blocking call anywhere in the OAuth refresh path can take the entire daemon down. The docs name "liveness/readiness" at `02_system_architecture.md:126-130` but do not define what "unhealthy" means, what the supervisor does, or how state is reconciled on restart. Related: the scheduler ensures "only one worker of a kind is active at a time" (`02_system_architecture.md:121-125`) but does not describe the locking mechanism, crash recovery for half-completed runs, or what happens when the daemon is killed mid-synthesis with uncommitted tool calls already logged in `wiki_log_entries`.

## Specific Critiques

**1. Reindex is not sufficient to fully recover the event layer, and the docs are honest about this but the operational implication is understated.**

`06_data_model.md:41-58` correctly states that `reindex` rebuilds `documents` + `documents_fts` + provenance + `wiki_log_entries` from `raw/` and `wiki/`. Critically, it then says "`events` cannot be rebuilt from files because there are no files per event" and directs you to re-run adapters with API replay. This is accurate, but the downstream effect is not fleshed out: **event retention at the source is your actual backup window**. If your SQLite is lost and GitHub only gives you 30 days of events, everything older than 30 days of GitHub activity is gone permanently unless it lives in git-local clones. `10_event_streams.md:37-61` documents the git-local salvage path, but there is no equivalent for Slack, Discord, Calendar, or Gmail where `raw/`-based long-term retention must exist or data is permanently lost on SQLite corruption.

**2. SQLite FTS5 contentless virtual tables are more fragile than the docs acknowledge.**

`06_data_model.md:171-186` specifies `documents_fts` as an external-content FTS5 table keyed by `documents.rowid`. `06_data_model.md:302-335` similarly defines `events_fts`. The documented `insert/update/delete` trigger pattern is correct (`06_data_model.md:180-186`), but: (a) if an external-content FTS5 index gets out of sync with the content table (after a crash between trigger fire and commit, partial WAL replay, or a VACUUM on a corrupted DB), you get silent result corruption with no checksum to detect it; (b) `rebuild`-based recovery is an O(N) full rescan and is not wired into `reindex` in the docs; (c) there is no health check that verifies `documents_fts` rowcount equals `documents` rowcount. The reindex command needs a `--fts-verify` or `--fts-rebuild` option, and a daemon-time integrity check on every start.

**3. Migration strategy is completely undocumented.**

`06_data_model.md` describes the current schema in detail but contains no section on schema versioning, `user_version` pragma use, forward/backward migration, rollback-on-failure, or online migrations while the daemon is running. Given the schema has already grown from `documents`/`documents_fts` in v1 to include `wiki_log_entries`, `wiki_claim_provenance`, `subscriptions_queue`, `events`, `events_fts`, `source_runs`, `source_adapters`, `workspaces`, and is explicitly planned to keep growing, you need: a `schema_version` row in a migrations table, ordered migration scripts, automatic on-startup migration with a backup-first policy, and a documented rollback for when a migration fails halfway through a large `events` table. None of this exists in the current docs.

**4. The daemon supervision model is underspecified.**

`02_system_architecture.md:72-130` and `02_system_architecture.md:272-278` list what the daemon does. The only failure reference is "daemon is supervised by the OS (systemd / launchd / Windows service stub)" (`02_system_architecture.md:276-278`), which punts the entire problem to the OS. A systemd `Restart=on-failure` will bounce the daemon on a crash, but: (a) if the crash is in the weekly temporal synthesis, the partial `wiki_log_entries` rows with uncommitted tool-call side effects stay in the DB; (b) there is no documented idempotency story for "synthesis run started at T, crashed at T+5min, daemon restarts at T+10s, should we resume / retry / skip until next week?"; (c) the `source_runs` table (`06_data_model.md:340-364`) tracks runs but the resumption semantics for a `running` row found on startup are not specified. You need a clear state machine: `pending -> running -> (succeeded|failed|abandoned)`, with a daemon-startup sweep that transitions orphaned `running` rows to `abandoned` and logs the interruption.

**5. Rate-limit back-pressure is named but not designed.**

`10_event_streams.md:102-118` and `05_source_integrations.md:98-180` describe per-adapter limits (GitHub 5k/hr, Slack tier-dependent, Gmail quota). `09_subscriptions_and_feeds.md` describes polling cadence. But there is no global rate-limit coordinator across adapters, no documented 429/529 retry-with-jitter policy, no circuit breaker for a persistently failing source, and no back-pressure to the scheduler that says "GitHub is rate-limited for 30 more minutes, skip the scheduled sync." The failure mode you should worry about: user installs fresh, daemon starts, all ~15 adapters fire their initial backfill at once, several hit their quotas, the daemon loops on retries, and the LLM usage budget is fine because nothing is synthesizing, but the logs flood with 429s and the user has no way to tell what is actually broken. You need a `RateLimiter` per provider with token-bucket semantics and a `CircuitBreaker` per adapter with a visible status in `llmwiki status`.

**6. LLM budget enforcement in the agent loop has a race window.**

`11_inference_endpoint.md:88-181` defines `[llm.budgets]` with per-operation and monthly caps, and `11_inference_endpoint.md:143-146` says "if a run exceeds a hard token cap, the loop stops, produces a partial draft labeled budget_exceeded, and writes a `wiki_log_entries` row of action=budget_stop." This is the right design intent, but the enforcement point matters: (a) if the check is between tool calls, a single unbounded tool call result (e.g., `wiki_read_section` on a 200k-token file) can blow past the cap before the next iteration; (b) if the check is after the model's response, the model's own completion can run over; (c) mid-run writes already committed to the filesystem via `wiki_write_section` tool calls are not rolled back when `budget_stop` fires. `12_conversation_capture.md:297-302` briefly discusses budget enforcement for conversation capture, but the general agent-loop case needs a pre-tool-call budget check plus a transactional "stage writes, commit on successful run end" pattern. Otherwise you get half-written wiki pages on every budget exhaustion.

**7. Secrets management has a critical gap for headless operation.**

[The reviewer's cited doc `08_config_and_secrets.md` does not exist; the critique applies to our de-facto secrets story distributed across docs.] The design is `~/.llmwiki/secrets/*.enc` encrypted with an OS-keyring-derived key. The design is reasonable for desktops but: (a) there is no passphrase-only fallback for headless Linux servers where no keyring daemon runs; (b) rotation of an individual credential appears to require a re-encrypt of the specific blob, but there is no documented `llmwiki secrets rotate <source>` flow; (c) revocation in the sense of "my GitHub PAT was leaked, invalidate the local copy and stop all GitHub adapters until a new one is set" is not a documented operation; (d) the `llm-usage.jsonl` log is explicitly designed to redact secrets but the docs do not say what tool-call logs in `wiki_log_entries` redact — a tool call argument that contained a token would leak into the provenance table.

**8. Conversation capture hook installation is a soft-lock hazard.**

`12_conversation_capture.md:152-208` describes installing `Stop` and `PreCompact` hooks into `~/.claude/settings.json` and Codex's `config.toml`. The hooks call `llmwiki capture conversation`. Failure modes: (a) if the llmwiki binary is missing/renamed/upgraded, every Claude Code session runs the failing hook on every Stop event and logs errors; (b) if the hook itself hangs (network call in ingestion, blocking on an LLM request), Claude Code may wait on hook completion before acknowledging the Stop — this kills interactive UX; (c) the `uninstall` path is not documented — if the user removes llmwiki, stale hooks stay in their settings files; (d) concurrent sessions writing to the same workspace with `sessionId` as the unique key (`12_conversation_capture.md:360-396`) rely on the client tool to give stable IDs, but Claude Code's `sessionId` behavior across `/resume`, `/compact`, and crashed sessions is not guaranteed stable and can produce duplicate or conflicting rows. The hook should be designed to be idempotent, non-blocking (spawn-and-detach), and have a documented `llmwiki hooks install|uninstall|verify` operation.

**9. Temporal synthesis kill switches are named but not designed.**

`10_event_streams.md:531-619` and `11_inference_endpoint.md:98-146` describe the weekly synthesis run with per-run budget, monthly cap, dry-run, draft-until-confirmed. This is good intent. Missing: (a) a hard "pause all synthesis" kill switch that survives daemon restart (e.g., a sentinel file at `~/.llmwiki/disable-synthesis`); (b) a "rollback the last run" operation that reverts all `wiki_log_entries` from a specific `run_id` and restores the affected wiki files from git (`06_data_model.md:242-268` implies wiki/ is git-versioned, but the rollback command is not documented); (c) a user-visible dashboard of "runs pending your review" with clear accept/reject UX — the docs say "draft until confirmed" but do not describe the confirmation surface.

**10. Observability is insufficient for field debugging.**

`~/.llmwiki/logs/{llm-usage,mcp-YYYY-MM-DD,sync-YYYY-MM-DD}.jsonl` is a reasonable start. Missing: (a) a structured daemon event log that correlates sync runs, LLM calls, and tool calls by `run_id` — right now debugging "the weekly synthesis failed, what did it do?" requires cross-joining three JSONL files by timestamp; (b) no span/trace model, so causality inside a single agent loop is lost; (c) no daemon-health metric endpoint (not Prometheus, just `llmwiki status --json` with scheduler state, adapter last-run/last-error, SQLite size, budget consumed, queue depths); (d) no structured panic/crash dump — a daemon segfault loses everything in memory and the systemd stderr is the only artifact.

## Missing Operational Pieces (Ranked)

1. **Schema migrations framework.** Highest risk: first incompatible v2 schema change will brick existing installs.
2. **Daemon supervision state machine.** Including orphaned-run recovery on startup.
3. **Global rate limiter + per-adapter circuit breakers.** With visible status.
4. **Backup command** that snapshots `~/.llmwiki/{raw,wiki,db,secrets,config}` atomically, including a documented restore procedure. Currently nothing exists; users are expected to rsync and hope.
5. **FTS5 integrity verification** on daemon start and as a flag to `llmwiki reindex`.
6. **`llmwiki hooks install|uninstall|verify`** for conversation-capture hook lifecycle.
7. **`llmwiki status --json`** with daemon health, adapter state, budgets, queue depths.
8. **`llmwiki synthesis pause|resume|rollback <run_id>`** as first-class operations.
9. **Passphrase-fallback secret unlock** for headless Linux without a keyring.
10. **Structured run-id correlation** across `llm-usage`, `mcp`, and `sync` logs.

## Recommendations

**Split the daemon into supervised subprocesses, not threads.** The scheduler, each adapter worker pool, the MCP HTTP server, and the web UI should be separate child processes supervised by a parent `llmwiki daemon` process with a restart policy per child. A crash in the weekly synthesis worker must not take the MCP HTTP server down. This is a real change to `02_system_architecture.md:72-130` but it is the single largest reliability win available. Communication is via SQLite (already the source of truth) plus a small IPC channel for liveness.

**Introduce a `schema_migrations` table and a `llmwiki db migrate` subcommand.** Use SQLite's `PRAGMA user_version` or a dedicated table. Every migration is an ordered file. Daemon startup checks version, refuses to start on a downgrade, runs pending migrations after taking an automatic DB backup to `~/.llmwiki/db/backups/pre-migration-YYYYMMDD.db`. Document the rollback policy: restore the backup, downgrade the binary.

**Add `llmwiki backup create|restore` as a first-class operation.** `create` produces a timestamped tarball of `raw/`, `wiki/` (via git bundle), `db/llmwiki.sqlite` (via `.backup` command, not file copy), `secrets/` (as-is, still encrypted), `config/`. `restore` refuses to run over a non-empty directory, verifies checksums, and replays. Document explicitly that `events` older than source-retention windows cannot be re-fetched — the backup is your only copy.

**Define the `source_runs` state machine and orphan sweep.** On daemon start, any `source_runs` row with `status=running` is transitioned to `abandoned` with a reason. The next scheduled run of that source picks up from the last successful checkpoint. For synthesis runs, `wiki_log_entries` rows from an abandoned run get a `superseded_by` pointer or are soft-deleted.

**Stage agent-loop writes in a run-scoped temp directory, commit on successful completion.** Tool calls like `wiki_write_section` write to `~/.llmwiki/runs/<run_id>/staged/` during execution. On `run_end=success`, the staged files are moved into `wiki/` and a git commit is made. On `run_end=budget_stop|error|abandoned`, the staged directory is moved to `~/.llmwiki/runs/<run_id>/failed/` for inspection and does not pollute `wiki/`. This fixes the mid-run corruption risk from critique #6.

**Ship a per-provider rate limiter and per-adapter circuit breaker from v1.** Token buckets configured from the adapter's documented limits. On 429/529, the adapter reports to the breaker; the scheduler sees the breaker state and skips or delays the next run. `llmwiki status` surfaces "GitHub: rate-limited, retry in 00:14:22."

**Make conversation-capture hooks idempotent and non-blocking.** The hook should be `llmwiki capture conversation --async` which spawns a detached subprocess and returns immediately. Add `llmwiki hooks install --client claude|codex|cursor`, `... uninstall`, `... verify` with explicit schema detection and a refusal to edit an unrecognized settings format.

**Add a single `llmwiki status --json` command** that returns daemon PID + uptime, each worker's last-run/last-error/next-run, adapter circuit-breaker state, current budget consumption vs cap, SQLite size + WAL size, last synthesis run_id and its review status, pending hooks-to-review queue. This is the minimum viable dashboard and everything else (web UI, MCP tool, prometheus exporter) builds on it.

**Introduce `run_id` correlation across all JSONL logs.** Every log line gets a `run_id` field. A single CLI subcommand `llmwiki logs show <run_id>` merges entries from all three log streams in timestamp order. This is cheap and makes post-mortem debugging tractable.

**Document the headless-server secrets flow explicitly.** Either (a) a passphrase-unlocked key stored at `~/.llmwiki/secrets/vault.key` where the passphrase is entered once at daemon start via systemd `LoadCredentialEncrypted=` or a TTY prompt, or (b) a documented integration with `pass`/`gpg-agent`/`age`. Pick one and write it down. The current "OS keyring" assumption silently breaks server installs.
