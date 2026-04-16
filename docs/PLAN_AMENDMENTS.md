# Implementation Plan Amendments — Round 1 (after first three-agent review)

> **Status:** Approved by all three reviewers (`llm-architect`, `ai-engineer`, `mlops-engineer`). Supersedes specific sections of `IMPLEMENTATION_PLAN.md`. The original plan stays in place as the long-form spec; this doc is the binding diff.

The first checkpoint review of the implementation plan produced findings from all three reviewers. Six BLOCKER findings and several IMPORTANT findings are reflected here. Implementation begins from the **amended** plan, not the original.

## The six BLOCKER findings, reflected

### B1 (llm-architect F1) — Split Phase 2 into 2a and 2b

**Original:** Phase 2 (~2.5 weeks) ships staged-write transaction + verifier + cascade + verbatim quote anchors + minimum viable Anthropic provider + `llmwiki ingest` end-to-end + tests with real Anthropic API.

**Amended:**

- **Phase 2a — Deterministic verifier and staged writes (~2 weeks).** Ships the staged-write envelope, verbatim quote anchor extraction with **versioned schema** (anchor_format_version field from day one), the verifier protocol with default strict implementation operating on **fixtures with pre-recorded LLM outputs**, the cascade workflow with `stage_merge`/`stage_hedge`/`stage_new_page`/`stage_cross_ref`, and the convergence-policy test (B5 below). **No live LLM calls.** The 10 capability floor sources commit here per llm-architect F9.

- **Phase 2b — Minimum viable Anthropic provider + live verification (~2 weeks).** Ships the MV Anthropic provider with streaming, error taxonomy (rate limit / auth / content policy / transport), retry policy, **mandatory prompt caching from day one** (B2 below), and **hardened budget enforcement** (B3 below). `llmwiki ingest` is wired end-to-end through the live provider. Tests against the real API run with hard per-test ceilings.

The strict-tier verifier rules are **code-frozen** at the end of Phase 2a. Any change to strict-tier rules in Phases 2b through 13 requires explicit documented justification and re-running the full capability floor.

### B2 (llm-architect F2) — Anthropic prompt caching is mandatory in Phase 2b

Prompt caching is not a Phase 8 optimization; it is a cost-governance mechanism for the verifier. The verifier's system prompt is sent on every verification call (1500-3000 tokens). Without `cache_control: ephemeral` on the stable system prefix, every verifier run during the inner development loop burns full input-token costs.

**Amended:** the MV Anthropic provider in Phase 2b ships with prompt caching enabled by default. The cache breakpoint sits at the end of the stable `tools + system` prefix, exactly where `research/raw/35_anthropic_prompt_caching.md` directs.

### B3 (llm-architect F3) — Budget enforcement hardened in Phase 2b

The original plan deferred the verifier multiplier and per-preset routing to Phase 8. The first real workspace run in Phase 2 against a 100-source workspace would trip 10× expected spend without these.

**Amended:** Phase 2b's `llm/budget.py` ships with three hard mechanisms:
1. **Verifier multiplier** as a config value (`verifier_budget_multiplier = 0.5` default), even if not yet automated by per-preset routing.
2. **Per-run hard ceiling** — the agent loop aborts before issuing the N+1th call if cumulative spend exceeds the configured cap.
3. **Pre-flight cost estimator** — `llmwiki ingest --dry-run` and `llmwiki synthesize --dry-run` print an estimated token + USD cost before committing. A real-money run above a threshold prompts for confirmation.

The full per-preset routing matrix from `11_inference_endpoint.md` still ships in Phase 8.

### B4 (mlops-engineer F1) — Secret rotation, revocation, audit log move from Phase 11 to Phase 4

Rotation is part of the basic vault contract, not a polish feature. The original plan put the basic vault in Phase 4 and rotation/revocation/audit in Phase 11 — a 3-month window during which users had real GitHub PATs in the vault with no rotation path.

**Amended:** Phase 4 ships the full secret vault contract:
- `llmwiki secrets set <ref>`
- `llmwiki secrets rotate <ref>` (keeps old value 7 days for unroll)
- `llmwiki secrets revoke <ref>` (wipes value, optionally disables dependent adapters)
- `llmwiki secrets list` (names + last-used, never values)
- `llmwiki secrets reveal <ref> --confirm` (audit-logged)
- `secrets/_audit.jsonl` append-only audit log

Migration `0004_add_sources_and_secrets.sql` includes the audit table.

### B5 (mlops-engineer F2) — Log redaction moves from Phase 11 to Phase 4

Phase 4 adapters log HTTP request/response data on errors. Without redaction, a 401 from GitHub trivially writes the full `Authorization: token ghp_...` header to disk in `~/.llmwiki/logs/`.

**Amended:** Phase 4 ships `secrets/redactor.py` with a regex-based pass over a known set of secret-header patterns (Bearer tokens, `Authorization: token`, `?api_key=`, `password=`, `client_secret=`, JWT shapes, GitHub PATs, OpenAI/Anthropic key prefixes). Every log emitter calls the redactor before writing. The full pattern library and per-secret-type detection still mature in Phase 11; Phase 4 ships the safety baseline.

### B6 (ai-engineer F1) — Phase 3 migration spec is required before Phase 2 ships any wiki content

The original plan had Phase 2 writing wiki content without belief sidecars and Phase 3 adding the belief layer on top — silent on whether Phase 2 content gets retroactively turned into beliefs.

**Amended:** Before Phase 2a closes, the Phase 3 belief migration is specified in writing as **option (a) — backfill on migration**. Phase 3's `wiki_beliefs` migration walks every existing wiki page from Phase 2, lifts each citation into a belief row with `valid_from = original_write_time`, and writes a sidecar JSON next to the page. Phase 2's citation schema is constrained to be lift-compatible: every citation must include the verbatim quote span (already required for the hash anchor), the section anchor, and enough metadata for the lift to be deterministic.

The Phase 3 migration is itself a database migration file (`0004` in the amended ordering, after the secrets table) and is tested against a fixture wiki built in Phase 2.

## IMPORTANT findings reflected in the amended plan

### I1 (mlops-engineer F3, F4, F6) — Backup, FTS integrity check, crash dumps move from Phase 11 to Phase 0

These three primitives are small, load-bearing, and expensive to ship late.

**Amended:** Phase 0 ships:
- **`llmwiki backup create [--output <path>]`** — uses SQLite's `VACUUM INTO` plus a tar of `~/.llmwiki/{secrets/,workspaces/,config.toml}`. ~30 lines.
- **`llmwiki reindex --fts-verify`** — uses FTS5's native `INSERT INTO documents_fts(documents_fts) VALUES('integrity-check')` plus a row-count comparison between content and FTS tables. ~20 lines.
- **`crash_dump.py`** — installs `sys.excepthook` that writes `~/.llmwiki/crashes/<iso8601>.json` with traceback + command + args + config path + Python version. ~40 lines.

The full backup with restore + verification, the content-hash FTS comparison, and the structured crash-dump-with-state-snapshot still mature in Phase 11; Phase 0 ships the safety baseline.

### I2 (ai-engineer F3) — M3 (verifier evasion rate) moves from Phase 9 to Phase 2

M3 is the only metric that does not depend on the belief layer. It can run against the verifier in isolation with an adversarial corpus.

**Amended:** Phase 2a ships:
- **20-30 hand-built fabrication test cases** at varying difficulty in `tests/fixtures/verifier_evasion/`.
- **A stripped-down M3 implementation** that runs the corpus through the verifier and reports catch rate per tier.
- **Phase 2 acceptance criterion:** ≥90% catch rate on tier-1 deterministic fabrications, ≥70% on tier-2 LLM-judged fabrications.

When M1+M2 ship in Phase 9, M3 is already in place; Phase 9 just adds the orchestration to run all three on schedule.

### I3 (mlops-engineer F5) — Phase 4 sync sweeps its own orphans

The original plan had Phase 4 shipping sources without the daemon (which arrives in Phase 6), creating a window where `source_runs` rows could accumulate in `running` state with no sweeper.

**Amended:** every `llmwiki sync` invocation begins with an orphan sweep against `source_runs`, transitioning any `running` rows to `abandoned`. The full daemon-startup sweep still ships in Phase 6 alongside the supervised-subprocess parent.

### I4 (mlops-engineer F7) — `runs` table logging from Phase 4

Phase 4's manual `sync` command must write a row to `runs` (the table from Phase 2) with `run_type='sync'`, `status`, `started_at`, `ended_at`, `triggered_by='cli:sync'`, `reject_reason` on failure. Structured logger and `run_id` correlation across log families still arrive in Phase 6, but the table-row primitive is table stakes.

### I5 (mlops-engineer F10) — Phase 6 splits into 6a and 6b

Phase 6 (~2.5 weeks) ships the supervised-subprocess parent, multi-child IPC, restart policy, kill switches, and the full observability stack. That is too much for one phase.

**Amended:**
- **Phase 6a — Single-child daemon (~1 week).** Parent process + one child (the scheduler) + heartbeat + graceful shutdown on SIGTERM + the daemon-startup orphan sweep.
- **Phase 6b — Multi-child + IPC (~1.5 weeks).** Adapter worker pool, MCP HTTP server, webhook receiver, full IPC, per-child restart policies, `llmwiki status --json`.

### I6 (mlops-engineer F11) — Phase 4 ships a minimum weekly self-report

Phase 4 sources run for 4-5 months before M1+M2 ship in Phase 9. To bridge the gap, Phase 4 writes a weekly summary to `~/.llmwiki/reports/weekly.md`: counts of documents ingested per source, error counts per source, top 10 slowest runs. Not M1+M2, but a minimum signal during the gap.

### I7 (llm-architect F4) — Phase 1 `guide` tool emits structured "not yet populated" messages

When Phase 1's `guide()` is called with no runs, no verifier, no eval data yet, the L1 dynamic sections must emit structured `{status: "not_yet_populated", available_in_phase: 2}` markers, not empty arrays or null. Phase 1's `guide()` also includes a top-level `phase: 1` field declaring which capabilities are wired and which are dormant, so a connected agent can read it and adjust.

### I8 (mlops-engineer F8) — Hooks ship with a protocol version from Phase 7

Hook scripts include a `LLMWIKI_HOOK_PROTOCOL_VERSION=1` line in their header. `llmwiki hooks verify` checks that installed hooks' protocol version matches the binary's expected version. `llmwiki hooks doctor` (added to the Phase 7 deliverable list) detects skew.

### I9 (mlops-engineer F9) — Rate limit test policy is committed in Phase 4

Per-adapter rule:
- Unit-level tests **avoid** triggering circuit breakers (use tiny budgets, canary endpoints, mocked clocks for the breaker state machine only).
- A separate integration test **explicitly triggers** the breaker with a synthetic burst against a safe endpoint.

Both kinds exist for every adapter. Stated as a Phase 4 test-design rule.

### I10 (llm-architect F7) — CI-specific strict budget mode + per-test ceilings

CI exports `LLMWIKI_CI_STRICT_BUDGET=1` which sets:
- Per-test wall-time ceiling: 30 seconds, killed mid-stream
- Per-test output token ceiling: 10 000 tokens, aborted mid-stream
- Per-CI-run total spend ceiling: $5 (configurable in CI secrets)

Above any of these, the test fails and the CI run aborts. Tail risk is bounded.

### I11 (ai-engineer F3 + llm-architect F10) — Verifier false-negative rate tracked from Phase 2

Phase 2's adversarial corpus also includes 10-15 **valid** quotes with formatting variations (em-dashes, smart quotes, indentation, NFC/NFD unicode). The verifier's false-negative rate on these is tracked alongside the catch rate. The test suite asserts false-negative rate ≤5%.

## The amended phase summary table

| Phase | Original | Amended |
|---|---|---|
| 0 | Skeleton | Skeleton + backup + FTS integrity + crash dumps |
| 1 | Read-only MCP | Read-only MCP + structured "not yet populated" L1 markers |
| 2 | Verifier + writes + Anthropic + ingest (2.5w) | **2a — deterministic verifier + cascade + 10 floor sources + adversarial corpus + M3** (2w) |
| | | **2b — MV Anthropic + caching + budget hardening + live verification + ingest** (2w) |
| 3 | Belief revision | Belief revision **with formal Phase 2 citation lift migration spec** |
| 4 | Sources + git-local + GitHub + secret vault basic | Sources + git-local + GitHub + **full secret vault (rotate, revoke, audit, redaction) + sync-orphan-sweep + runs-table logging from CLI + weekly self-report + freeze-ceiling phase gate** |
| 5 | RSS + IMAP | RSS + IMAP (no change) |
| 6 | Daemon + scheduler + observability (2.5w) | **6a — single-child daemon + scheduler + heartbeat + orphan sweep** (1w) |
| | | **6b — multi-child + IPC + MCP HTTP + webhook + status --json** (1.5w) |
| 7 | Conversation capture + hooks | Conversation capture + hooks + **hook protocol version + hooks doctor** |
| 8 | Multi-provider + scheduled synthesis | Multi-provider (caching already in 2b) + scheduled synthesis + **per-preset routing matrix completion** |
| 9 | M1-M5 | M1, M2, M4, M5 (M3 already in 2a) + freeze-ceiling validation pass |
| 10 | Calendar + Gmail + Slack + Notion + Cloud | (no change beyond freeze-ceiling validation) |
| 11 | Backup + restore + rotation + redaction + crash + FTS verify | **Restore + full rotation lifecycle + audit log enhancements + crash-dump state snapshot + FTS content-hash comparison + DR drill** |
| 12 | Docs + packaging + release | (no change) |

**Total estimate revision:** 22-26 weeks → **24-29 weeks**. The split phases add roughly 1-2 weeks of total work because the splits introduce review checkpoints that catch issues earlier.

## Approval

This amended plan has been reviewed and approved by:
- `llm-architect` — the Phase 2 split, mandatory caching, and budget hardening close the load-bearing concerns.
- `ai-engineer` — the M3 move to Phase 2, the cascade convergence test specification, and the explicit Phase 3 migration spec close the AI-quality concerns.
- `mlops-engineer` — the Phase 4 secret rotation + log redaction, the Phase 0 backup + FTS check + crash dumps, and the Phase 6 split close the operational concerns.

Implementation begins at Phase 0.
