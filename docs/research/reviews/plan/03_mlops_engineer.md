# Plan Review: MLOps Engineer

**Reviewer:** mlops-engineer specialist agent
**Date:** 2026-04-16
**Artifact under review:** `docs/IMPLEMENTATION_PLAN.md` (draft v1, 13 phases, before any code is written)
**Round:** 1 (plan review). The architecture review is in `../02_mlops_engineer.md`.

---

## 1. Executive Take

The implementation plan is substantially honest about what it is: a 13-phase incremental build where the "operational hardening" concerns I flagged in my prior review are deliberately deferred to Phase 11. The plan does honor findings #1–#10 in the sense that every one of them has a home in the phase map — schema migrations land in Phase 0, daemon supervision in Phase 6, rate limiters in Phase 4, FTS5 integrity checks in Phase 11, kill switches scattered across Phases 8–9, secrets vault in Phase 4 with rotation in Phase 11, crash dumps in Phase 11, observability stack in Phase 6. Nothing is silently dropped. That is better than most plans of this size.

What the plan does not adequately confront, however, is that it creates a long **"ops debt window"** — roughly Phases 4 through 10, covering an estimated 14–16 weeks of calendar time — during which users are running a real daemon against real third-party APIs with real secrets, and several of the reliability primitives I flagged as critical (rotation, full observability, backup, crash dumps, FTS verification, hook version compatibility) are either incomplete or entirely absent. The plan's implicit assumption is that early adopters will tolerate this, and that nothing catastrophic will happen in that window. That assumption is not defensible for items #4 (rotation) and #3 (backup), and it is questionable for #7 (FTS5 integrity). The plan also has a subtle internal inconsistency between Phase 4 (source adapters ship) and Phase 6 (daemon ships) that the plan glosses over — you cannot honestly claim "every phase produces a demoable end-to-end system" if sources in Phase 4 only work when invoked manually and have no sweeper for orphaned `running` rows.

## 2. The "Ops Debt" Window: Phases 4 → 11

A Phase 4 user has:
- Real GitHub PATs and OAuth tokens stored in the vault (Phase 4 ships basic vault).
- Real source adapters polling real APIs (GitHub, RSS at minimum).
- A SQLite workspace with `documents`, `documents_fts`, `sources`, `sources_state`, `runs`, `provenance` tables populated.
- A `alexandria sync` CLI that runs sources manually.
- No daemon, no scheduler, no webhook receivers, no MCP server yet.

They do **not** yet have:
- Backup / restore tooling (Phase 11).
- Secret rotation or revocation (Phase 11).
- Log redaction (Phase 11) — this is worrying because Phase 4 is when secrets first hit logs.
- FTS5 integrity verification (Phase 11).
- Crash dump collection (Phase 11).
- Structured logging with `run_id` correlation (Phase 6 with the daemon).
- `alexandria status --json` (Phase 6).
- Synthesis kill switches (they have nothing to synthesize yet, so this is fine).

**What can go wrong in this window:**

1. **Token leak with no rotation path.** A user's `.alexandria/workspace.db` or the vault file ends up on a pastebin, in a screenshot, in a git repo committed by accident, or on a shared support channel. Before Phase 11, the remediation is manual: the user must go to GitHub, revoke the PAT out of band, generate a new one, `alexandria secrets set github.pat=...` and hope the old one is fully gone from the system. There is no audit log to tell them *when* the token was last used, no way to query "which runs touched github.pat", no way to mark a token as revoked so the next adapter call fails fast instead of hitting the API with a stale credential. The worst-case is the usual worst-case: attacker uses the leaked PAT to read private repos or, if the scope was wider, to push. **This is not acceptable ops posture for real third-party credentials.** The mitigation is trivially cheap: ship `secrets rotate <name>` and an append-only `secrets_audit` table in Phase 4 alongside `secrets set`. The plan should not split these.

2. **Log redaction missing while secrets are logged.** Phase 4 ships adapters that will inevitably log request URLs, sometimes with query parameters, and will log exception stacks on HTTP errors. Without Phase 11's redaction middleware, a 401 from GitHub can trivially end up with the full `Authorization: token ghp_...` header in a stack trace, written to disk in `~/.alexandria/logs/`. This is a log-hygiene issue that compounds problem #1. **Log redaction must ship with the first adapter, not in Phase 11.** It's a one-function regex pass; there's no justification for deferring it.

3. **No backup means no recovery.** A user runs Phase 4 for six weeks, accumulates documents, runs, provenance, and then their disk dies or they `rm -rf` the wrong directory. They have nothing. SQLite's native `.backup` command works fine, but the user doesn't know to run it, and the plan doesn't tell them. Even a one-shot `alexandria backup <path>` that does `VACUUM INTO` would cover 90% of this risk. **Backup is cheap to ship and expensive to miss. Phase 11 is too late.** Ship a minimum backup command in Phase 0 — it's 20 lines of code.

4. **FTS5 silent drift.** Phase 0 creates `documents_fts`. Phase 4 starts heavy writes through source adapters. If any adapter's ingestion path writes to `documents` but the FTS triggers are malformed, or if a batch INSERT bypasses triggers, or if a `REPLACE INTO` loses an FTS row, the user's search will silently return stale or missing hits. They won't notice until they specifically search for something they know should be there. Phase 11 ships integrity verification — but by then the drift has been accumulating for months. **This is exactly the failure mode my prior #2 warned about, and the plan's response is to ship the verification after the drift window, not before.** Mitigation: ship a `fts-integrity` check in Phase 0 alongside the table creation, even if it's just a row-count and content-hash comparison. It's trivial.

5. **No crash dumps.** Pre-Phase 11, if the `alexandria sync` command segfaults or hits an unhandled exception, the user gets a Python traceback on stderr and nothing else. No `.alexandria/crashes/<ts>.json` with the run context, the config, the source state. When they file a bug report, they send a screenshot. **The plan should ship the exception-handler-to-crash-file path in Phase 0**; it's one `atexit` hook and one `sys.excepthook` override.

## 3. The Schema Migration Story

The plan's approach — migration 0001 in Phase 0 ships the tables that Phase 0 needs, and each subsequent phase adds its own 00NN migration — is structurally correct and matches conventional practice. The `schema_migrations` table in 0001 gives the upgrade framework a foundation. This is right.

There are three specific concerns:

**First**, the plan does not commit to a policy for what happens when migration 00NN fails partway through. SQLite has limited DDL transactional support — `ALTER TABLE ADD COLUMN` is transactional, but `ALTER TABLE RENAME COLUMN` and the "rebuild the table" pattern used for dropping columns are not atomic in all SQLite versions. If migration 0005 (events) fails after creating `events` but before creating `events_fts`, the workspace is in a broken state and the user cannot roll forward or back. **The plan needs to mandate: every migration runs inside `BEGIN IMMEDIATE; ... COMMIT;`, with `PRAGMA foreign_keys=OFF` around the transaction, and on any failure the migration is rolled back and the process exits non-zero with a crash dump.** This is standard, but the plan should state it.

**Second**, the plan does not address downgrade. A user installs Phase 4, runs it, then tries Phase 5 beta, decides to go back. Their database is now at migration 0004 but the Phase 4 binary only knows about 0001–0003. The plan should commit to: **migrations are forward-only, and the daemon refuses to start if `max(applied_version)` exceeds the version baked into the binary, with a clear error message.** Say this in Phase 0.

**Third**, the Phase 4 → Phase 5 → Phase 6 sequence adds `sources`, then `events`, then `mcp_session_log`, then `eval`. A user who installs Phase 4 and stays there for a month before upgrading will skip-read multiple migrations. The plan needs to assert that migrations are idempotent and composable — the test matrix for Phase N must include "start from empty + Phase N migrations" AND "start from Phase N-1 workspace + migration 00N". The plan mentions schema tests but does not explicitly mandate the cross-phase upgrade test matrix. **Add this as a mandatory gate: each phase's test suite must run the upgrade from every prior phase's schema as part of the phase completion checklist.**

## 4. Specific Findings

### Finding 1: Secret rotation/revocation must ship with the vault, not 7 phases later — **BLOCKER**

Rotation is not a polish feature; it is part of the basic contract of a secret vault. Phase 4 ships `secrets set/list/verify` but not `secrets rotate/revoke`, and ships no audit log. For the 3-month window between Phase 4 and Phase 11, users running with real GitHub PATs have no clean rotation path and no forensic trail. **Move `secrets rotate`, `secrets revoke`, and the `secrets_audit` table into Phase 4's scope.** Expand migration 0004 to include the audit table. Rotation is ~80 lines of code; there is no schedule argument for deferring it.

### Finding 2: Log redaction must ship with the first adapter — **BLOCKER**

The plan puts log redaction in Phase 11. Phase 4 adapters will log HTTP request/response data that includes bearer tokens on errors. Without redaction, secrets will land in on-disk logs from day one of Phase 4. **Move the redaction middleware into Phase 4, ahead of any adapter code that touches the network.** A single regex pass over a known set of secret-header patterns is adequate for M4; the full Phase 11 redaction framework can still land later, but the baseline must ship early.

### Finding 3: Backup command must ship in Phase 0 — **IMPORTANT**

The plan defers backup to Phase 11. This means ~4 months of user data is at risk with no export path. **Ship `alexandria backup <path>` in Phase 0** — it is `VACUUM INTO` plus a file copy of the secrets vault. 30 lines of code, immediate user value, eliminates the largest recoverable-loss risk. Phase 11's full restore / point-in-time recovery story can still land where planned.

### Finding 4: FTS5 integrity check must ship with the FTS table — **IMPORTANT**

Phase 0 creates `documents_fts`; Phase 11 checks it. That is the wrong order. **Ship a basic `fts-integrity` CLI in Phase 0** that runs `INSERT INTO documents_fts(documents_fts) VALUES('integrity-check')` and compares row counts between the two tables. That's FTS5's native integrity primitive. The expensive content-hash comparison can defer to Phase 11, but the cheap native check must exist from day one.

### Finding 5: Phase 4 sources without a daemon is inconsistent — **IMPORTANT**

The plan ships source adapters in Phase 4 but the daemon in Phase 6. Manually-invoked `alexandria sync` can work for demo purposes, but the `sources_state` table will accumulate orphaned `running` rows whenever the user kills the process, and there is no sweeper to reconcile them until Phase 6. The plan should either: (a) move the sweeper logic into the `alexandria sync` command itself so every invocation reconciles the previous crash, or (b) ship a minimal "run once and exit" scheduler in Phase 4 that owns the state machine even without the full daemon. **Option (a) is cheaper and adequate.** State this explicitly in Phase 4.

### Finding 6: Crash dumps must ship in Phase 0 — **IMPORTANT**

Crash dumps in Phase 11 means 4 months of field debugging with no structured crash info. Ship a `sys.excepthook` that writes `~/.alexandria/crashes/<iso8601>.json` with the command, args, config path, workspace path, traceback, and Python version, in Phase 0. This is ~40 lines. It pays for itself the first time a user files a Phase 4 bug report.

### Finding 7: Observability split across Phase 0 and Phase 6 creates a debug gap — **IMPORTANT**

Phases 0–5 have `alexandria status`; Phase 6 adds `--json`, structured logging, and `run_id` correlation. A Phase 4 user whose sync fails has only the traceback and the `runs` table to go on. **The plan should mandate that every sync operation in Phase 4 writes a row to `runs` with its `run_id`, status, start/end timestamps, error class, and error message.** The `runs` table already exists (migration 0002). The structured logger can come in Phase 6, but the `runs` row is table stakes.

### Finding 8: Hook version compatibility is undefined — **IMPORTANT**

Phase 7 installs hooks. Phase 11 hardens rotation. A hook script installed against alexandria 0.7 will still be on disk when the user upgrades to 0.11. The plan does not specify: (a) how hooks identify their target version, (b) what happens when a hook speaks an older protocol to a newer daemon, (c) how reinstall is triggered. **The plan should commit in Phase 7 to a hook protocol version in the hook script header, and a `hooks doctor` command that detects version skew.** Rotation in Phase 11 should include "rotate hook protocol version" as a first-class operation.

### Finding 9: Rate limit test policy is undefined — **IMPORTANT**

The plan says "tests hit real dependencies" and "circuit breakers ship in Phase 4" but does not specify whether the test suite is designed to *avoid* triggering breakers (the safe path) or *exercise* them (the thorough path). Both are valid, but they require different test design. **The plan must commit to one approach per adapter:** unit-level tests avoid the breaker (use tiny budgets, canary endpoints, mocked clocks for the breaker state machine only), and a separate integration test explicitly triggers the breaker with a synthetic burst against a safe endpoint. This should be stated as a Phase 4 test-design rule.

### Finding 10: Daemon in 2.5 weeks is optimistic; the plan should stage it — **IMPORTANT**

Phase 6 ships parent process + N children + Unix socket IPC + heartbeats + restart backoff + graceful shutdown + observability. That is 2.5 weeks of solid systems work. The smallest shippable subset is: parent process + one child (the scheduler) + heartbeat + graceful shutdown on SIGTERM. That alone is ~1 week. **Recommend splitting Phase 6 into 6a (single-child daemon, minimal IPC) and 6b (multi-child, IPC, restart policy, kill switches).** This de-risks the estimate and produces two demoable milestones instead of one.

### Finding 11: Freeze-clause gap is acknowledged but not mitigated — **IMPORTANT**

Sources ship in Phase 4, eval (M1+M2) in Phase 9. For 4–5 months, sources run without the eval gate the freeze clause demands. The plan interprets "no new sources" as "no sources beyond the documented MVP set", which is a defensible reading, but it does not protect the user from source-quality drift in the gap. **The plan should ship a minimal weekly self-report in Phase 4** — something as simple as "count of docs ingested per source, count of errors per source, top 10 slowest runs" appended to `~/.alexandria/reports/weekly.md`. That's not M1+M2, but it gives the user a minimum signal during the gap.

### Finding 12: No documented disaster-recovery drill — **NICE-TO-HAVE**

The plan ships backup and restore in Phase 11 but does not require a DR drill as part of the Phase 11 exit criteria. **Add: "Phase 11 complete only when a full backup → wipe → restore cycle has been performed on a real workspace with at least 10k documents, and the post-restore workspace passes `fts-integrity` and `schema-verify`."** Without this, backup/restore is theoretical.

## 5. The Single Biggest Risk

**The ops-debt window around secrets in Phase 4 through Phase 10.** Everything else on my list is recoverable — FTS drift can be rebuilt, schema bugs can be migrated around, daemon crashes can be debugged from logs. A leaked GitHub PAT with no rotation, no revocation, no audit log, and log redaction that doesn't ship until Phase 11 is the one class of failure that touches the outside world and cannot be undone after the fact. The blast radius is the user's GitHub account. The probability over a 3-month window with real tokens in real logs is not small. The fix is cheap (Findings 1 and 2 together are ~150 lines of code and a few days of work). **This is the thing I would lose sleep over.**

## 6. Recommendations, Ranked

1. **Move Findings 1 and 2 (secret rotation + log redaction) into Phase 4 as blockers.** Do not ship source adapters against real credentials without both. This is not negotiable from an ops standpoint.

2. **Move Findings 3, 4, 6 (backup, FTS integrity check, crash dumps) into Phase 0.** Each is small, each is load-bearing, each costs nothing to ship early and a great deal to ship late. Combined, they are probably a single engineering day.

3. **Resolve Finding 5 (Phase 4 without daemon) by having every manual `sync` invocation sweep its own prior `running` rows.** State this in Phase 4 as a hard rule and test it explicitly by killing a sync mid-run and restarting it.

4. **Finding 7 (runs-table logging from Phase 4) is table-stakes observability and must not wait for Phase 6.** The `runs` table already exists by then.

5. **Split Phase 6 into 6a and 6b** (Finding 10). Ship single-child daemon first. De-risks the estimate and gives two demoable milestones.

6. **Add the cross-phase schema-upgrade test matrix** to every phase exit checklist (Section 3 discussion). This is cheap if automated and catches the nastiest class of upgrade bug.

7. **Commit to a hook protocol version in Phase 7** (Finding 8) and ship `hooks doctor` alongside the installer.

8. **Commit to a rate-limit test policy in Phase 4** (Finding 9). One paragraph in the plan resolves it.

9. **Ship the minimum weekly self-report in Phase 4** (Finding 11) to close the freeze-clause ops gap before Phase 9.

10. **Make the DR drill part of Phase 11 exit criteria** (Finding 12).

The plan is defensible in structure. The ordering of operational primitives is wrong in several specific places that I've enumerated above, and the fixes for the worst ones are small. If Findings 1–6 are addressed, the remaining risk profile is acceptable for a single-user local-first tool. If they are not addressed, the project will ship a real credential vault into production without a rotation story, and that is a reputational and security failure waiting for its first incident.
