# 13 — Hostile Verifier and Staged Writes

> **Cites:** `research/reviews/03_ai_engineer.md` (R1, R2, R3, §3.1, §3.2, §3.3, §3.4, §5), `research/reviews/01_llm_architect.md` (§2.6), `research/reviews/02_mlops_engineer.md` (#6, recommendation on staged writes).

## The single biggest gap this doc closes

> *"There is no adversarial check on the guardian's own output. Every correctness mechanism — citation validation, cascade completeness, lint, synthesis — runs inside the same LLM context that did the write."* — `reviews/03_ai_engineer.md`, §5

The guardian is simultaneously the ingest worker, cascade planner, citation validator, lint executor, and synthesis engine. A language model reviewing its own output has structural confirmation bias that no prompt can eliminate. This doc defines **the single mechanism** that removes that bias: a staged-write transaction that routes every wiki write through an independent hostile verifier agent before commit.

Four concerns — citation fabrication, partial cascade corruption, synthesis crash recovery, mid-run budget exhaustion — all collapse into this one abstraction. DRY: one mechanism, four concerns closed. KISS: no new vocabulary beyond "staged run" and "verifier verdict."

## The abstraction: staged write transaction

Every wiki write — from an interactive MCP session, a CLI batch operation, or a daemon-driven scheduled synthesis — is wrapped in a **run**. A run is a short-lived, atomic, inspectable unit with exactly three final states: `committed`, `rejected`, `abandoned`.

```
                     ┌───────────────────┐
 write plan ────────▶│  stage (pending)  │
                     └─────────┬─────────┘
                               │
                         verifier pass
                               │
                     ┌─────────┴─────────┐
                     │                   │
                     ▼                   ▼
                commit verdict    reject verdict
                     │                   │
                     ▼                   ▼
          ┌──────────────────┐  ┌──────────────────┐
          │ atomically move  │  │ move to failed/, │
          │ to wiki/ + git   │  │ log, return      │
          │ commit + sqlite  │  │ reason to caller │
          │ state flush      │  │                  │
          └──────────────────┘  └──────────────────┘
```

### On-disk layout

```
~/.alexandria/runs/<run_id>/
├── meta.json           # run_id, started_at, triggered_by, workspace, verifier_preset
├── plan.json           # the full write plan (ops + targets + staged content hashes)
├── staged/             # proposed changes, mirrors wiki/ layout
│   ├── topics/
│   │   └── auth.md
│   └── overview.md
├── verifier/
│   ├── prompt.md       # the exact prompt sent to the verifier
│   ├── verdict.json    # {verdict, per_claim_findings, per_page_findings, reasoning}
│   └── transcript.jsonl
└── status              # pending | verifying | committed | rejected | abandoned
```

On commit, `staged/` is moved into the workspace's `wiki/` via `git mv` followed by `git commit`. On reject, the whole directory moves to `~/.alexandria/runs/<run_id>/failed/` for inspection. On abandon (daemon crash, SIGKILL, etc.), a startup sweep transitions orphaned runs to `abandoned` and moves them to `failed/` without rollback — the wiki is untouched because nothing was ever moved out of `staged/`.

### SQLite state

One new table:

```sql
CREATE TABLE runs (
  run_id           TEXT PRIMARY KEY,
  workspace        TEXT NOT NULL REFERENCES workspaces(slug),
  triggered_by     TEXT NOT NULL,          -- 'mcp:<tool>' | 'cli:<cmd>' | 'daemon:<job>'
  run_type         TEXT NOT NULL,          -- 'ingest' | 'cascade' | 'synthesis' | 'lint' | 'archive'
  status           TEXT NOT NULL,          -- 'pending'|'verifying'|'committed'|'rejected'|'abandoned'
  started_at       TEXT NOT NULL,
  ended_at         TEXT,
  verifier_preset  TEXT,                   -- llm preset used for verification
  verdict          TEXT,                   -- 'commit'|'reject'|'revise' (null until verifier ran)
  reject_reason    TEXT,
  loop_count       INTEGER NOT NULL DEFAULT 1,
  budget_input_tokens_used  INTEGER DEFAULT 0,
  budget_output_tokens_used INTEGER DEFAULT 0,
  budget_usd_used  REAL DEFAULT 0,
  CHECK (status IN ('pending','verifying','committed','rejected','abandoned'))
);

CREATE INDEX idx_runs_workspace_started ON runs(workspace, started_at DESC);
CREATE INDEX idx_runs_status_started    ON runs(status, started_at DESC);
```

Runs span every path that writes to the wiki layer. `source_runs` in `06_data_model.md` remains the sibling table for external-source sync runs (SQL layer: source_runs ≠ runs). Runs are for **guardian writes**; source_runs are for **adapter reads from external APIs**.

## The verifier agent

The verifier is not a separate service — it is **the same agent loop runner** as the daemon-owned synthesis engine from `11_inference_endpoint.md`, just invoked with different parameters. DRY.

### Interface (single responsibility)

```python
class Verifier(Protocol):
    """Review a staged write plan and vote commit/reject/revise."""

    async def verify(
        self,
        run_id: str,
        workspace: str,
        plan: WritePlan,
        staged_dir: Path,
    ) -> VerifierVerdict: ...


class VerifierVerdict(BaseModel):
    verdict: Literal["commit", "reject", "revise"]
    reasoning: str
    per_claim_findings: list[ClaimFinding]   # each with status, source, note
    per_page_findings: list[PageFinding]
    tokens_used: Usage
```

One abstract method. One return type. Open/Closed: new verifier strategies (stricter hostile prompt, rule-based pre-check, ensemble vote) can be dropped in without changing callers.

### Contract the default verifier honors

1. **Fresh context.** No read access to the writer's conversation history, no memory of prior runs. The verifier is always spawned with a new LLM session.
2. **Read-only tool surface.** `list`, `grep`, `search`, `read`, `follow`, `events`, `history`. No `write`, `delete`, `str_replace`, or anything else that mutates state.
3. **Staging-aware reads.** The verifier's `read` tool serves staged content when asked for a staged path, so it reviews exactly what would land in the wiki — not what is currently on disk.
4. **Hostile prompt.** The system prompt names the job: *find the error in this write*. Not *review this write*. The framing matters.
5. **Bounded effort.** Same budget machinery from `11_inference_endpoint.md` — per-run input/output token caps, hard USD ceiling, dry-run mode. Default: half the writer's budget because the verifier's job is narrower.

### The verifier's checks

Per-claim checks (run once per footnote citation):

1. **Syntactic citation format.** Parseable `[^N]: filename, p.X`.
2. **Source existence.** Cited file is in `raw/<adapter>/...`. Fail if missing.
3. **Verbatim quote anchor (see below).** Cited span's SHA-256 hash exists in the current raw source at the recorded page offset. Fail if hash missing (source was edited) or hash present but span content changed.
4. **Semantic support.** The verifier reads the cited span and votes on whether it supports, partially supports, or contradicts the claim.

Per-page checks (run once per staged file):

1. **Schema.** Frontmatter matches `06_data_model.md` conventions, required fields present.
2. **Orphan detection.** The page is reachable from `wiki/index.md` or linked from another page.
3. **Cross-reference integrity.** Every `[[wiki-link]]` and markdown link resolves.

Per-run checks (once per cascade):

1. **Coverage.** Pages grep'ed for the source's key terms match the pages the plan touched. Missing coverage is a finding, not a reject — the verifier notes it and the verdict decides.
2. **Convergence policy compliance** (see `15_cascade_and_convergence.md`). If the plan overwrites a claim without applying the dated hedge marker, it is a reject.
3. **No raw/ writes.** Path ACL violation is a reject.
4. **Budget attestation.** The writer's token and USD counts fall within the run's declared budget.

### Verdict semantics

- **commit** — all checks passed; the run moves to `committed` and staged → wiki.
- **reject** — at least one critical check failed (missing source, hostile path, fabricated quote anchor, convergence policy violation, partial cascade that leaves the wiki worse than before). The run moves to `rejected`. `failed/` holds the staging for inspection. The caller receives a structured reason.
- **revise** — non-critical findings (weak semantic support on 2 of 20 claims, a missing cross-ref). The writer is fed the findings as a new turn, bounded by `MAX_LOOPS = 3`. Past 3 loops, the run is rejected even if findings are non-critical.

The three outcomes are the only branches. KISS.

### Manual override

Humans can override a reject with `alexandria verify override <run_id> --reason "..."`. This moves the run from `rejected` to `committed` and records the override in `runs.verdict = 'commit_override'`. Overrides are visible in `alexandria status` and in weekly M1 reports from `14_evaluation_scaffold.md`. If M1 shows that overrides correlate with citation-fidelity drops, the eval scaffold surfaces the correlation.

## Verbatim quote anchors

Closes ai-engineer R2 and §3.4. The `wiki_claim_provenance` table in `06_data_model.md` gets three new columns:

```sql
ALTER TABLE wiki_claim_provenance ADD COLUMN source_quote TEXT;
ALTER TABLE wiki_claim_provenance ADD COLUMN source_quote_hash TEXT;  -- sha256 of source_quote
ALTER TABLE wiki_claim_provenance ADD COLUMN source_quote_offset INTEGER;  -- char offset in source file
```

When the writer creates a wiki claim, it must provide the verbatim text span from the source. The span is stored as `source_quote`, hashed into `source_quote_hash`, and located by char offset. The verifier's check #3 is a **deterministic local check**: `sha256(raw_file[offset : offset + len(source_quote)]) == source_quote_hash`. No LLM judgment. No round trip.

**Semantic check #4 still runs** (is the quote actually supportive?), but the cheap deterministic check #3 catches the most common failure mode — a hallucinated filename + page number — before the LLM is involved.

When a raw source is re-synced and its content changes, the old hash stops matching. Lint (`04_guardian_agent.md`) surfaces the drift as a "source drifted" finding. The writer can re-anchor on the next cascade; the convergence policy in `15_cascade_and_convergence.md` says to preserve both the original claim with its original anchor AND a new claim with the updated anchor, dated.

## Cascade as a transaction

Closes ai-engineer R3 and §3.2. The `str_replace` exactly-one-match primitive in `04_guardian_agent.md` is unchanged — **surgical edits remain surgical**. The transaction boundary lives one layer up: **the cascade plan, not the individual replacement, is the unit of commit**.

Workflow:

1. The guardian plans the cascade: N edits across M files, stored in `runs/<run_id>/plan.json`.
2. The guardian applies every edit to **staged copies** of the affected files in `runs/<run_id>/staged/`, not to the live `wiki/`. Each `str_replace` still requires exactly-one-match, but the target is the staged copy.
3. If any single replacement fails (no match, multi-match, or a sub-step error), the entire run aborts with verdict `reject`. The live `wiki/` is untouched because nothing was ever moved out of `staged/`.
4. On success across all N edits, the verifier runs against the full staged set.
5. On `commit` verdict, the whole staging directory is moved into `wiki/` atomically via `git mv` + `git commit -m "alexandria run <run_id>"`.

Half-cascades become impossible. Either the whole plan lands or none of it does. This is the DRY win — there is no separate "cascade transaction" mechanism; it is the same staged-write transaction.

## Synthesis run envelope — already covered

Closes llm-architect §2.6. The synthesis runs in `10_event_streams.md` and `11_inference_endpoint.md` are just a specific kind of run (`run_type = 'synthesis'`). They use the same staging, same verifier, same commit semantics. A daemon crash mid-synthesis leaves a `pending` or `verifying` run; the startup sweep transitions it to `abandoned` and moves its staging to `failed/`. The user sees it in `alexandria synthesize review` and decides whether to re-run.

No new concepts. No cross-store transaction. No orphan cleanup that disagrees with the filesystem. One mechanism, one code path.

## Mid-run budget exhaustion — already covered

Closes mlops #6. The writer's budget enforcement lives in `11_inference_endpoint.md`. When the budget is exhausted mid-run, the writer stops. The run status becomes `pending` but with no verifier pass. Startup sweep or the run's own timeout handler transitions it to `abandoned`. Staging goes to `failed/`. The live `wiki/` is clean.

**No partial writes can ever pollute the live wiki.** This invariant holds because `wiki/` is only touched on the `committed` branch of the verdict, and the verdict requires a complete verifier pass. Any budget exhaustion prevents the verdict from being reached.

## Cost and SLA

The verifier roughly doubles inference cost for every guardian write. This is the price of correctness. `11_inference_endpoint.md` is updated to:

1. Add a `verifier` preset in `[llm.presets]` (defaults to a cheaper model — Sonnet rather than Opus — because the verifier reads and votes, it doesn't plan and write).
2. Add a `verifier_budget_multiplier` field in `[llm.budgets]` (default 0.5, meaning the verifier gets 50% of the writer's budget).
3. Track verifier token spend separately in `llm-usage.jsonl` so M4 (cost characterization) can separate writer cost from verifier cost.

### When the verifier is not run

Three exceptions, each explicit:

1. **Structural pages in trusted contexts.** `write(append)` to `wiki/log.md` from the guardian's own operation logs is exempt — the log is append-only, tiny, and never cited. Its content comes from the run's own metadata, not from user source material.
2. **User manual override.** `alexandria ingest --no-verify <source>` runs the writer without the verifier pass, for users who want the speed and trust themselves. The run is marked `unverified` in the `runs` table and the weekly M1 report counts unverified runs separately.
3. **Draft mode.** `alexandria synthesize --workspace X --draft-only` produces a run that stops at `status = pending` without committing or verifying. The user reviews the staging directly via `alexandria runs show <run_id>`. This is the dry-run path upgraded into a real staging run.

All three exceptions are OFF by default and must be explicitly requested.

## SOLID application

- **Single Responsibility.** The verifier does one thing: vote on a staged plan. The staging mechanism does one thing: hold writes until verdict. The run table does one thing: track the state machine.
- **Open/Closed.** Adding a new check to the verifier's check list does not change the interface. Adding a new run_type (`rehearse`, `experiment`, `migrate`) does not change the runs table beyond the enum.
- **Liskov Substitution.** Any `Verifier` implementing the protocol can replace the default. Useful for (a) rule-based cheap pre-checks that run before the LLM verifier, (b) ensemble voting across multiple providers, (c) faster local-only verification for tests.
- **Interface Segregation.** The writer depends only on `stage_write(run_id, path, content)` and `finalize_run(run_id)`. It does not know about verification internals, SQLite schema, or git commit details.
- **Dependency Inversion.** The verifier is injected into every write path. Default implementation uses the configured provider (`11_inference_endpoint.md`); unit tests can substitute a `FakeVerifier` that always votes commit or reject.

## What this doc does NOT cover

- The actual **ingest workflow** (plan → read → draft → stage → verify → commit) lives in `04_guardian_agent.md`'s updated workflow section. This doc defines the transaction shape the workflow uses.
- The **cascade convergence policy** (hedge with dated marker when sources disagree) lives in `15_cascade_and_convergence.md`. The verifier's check #2 at the per-run level references that policy.
- The **evaluation metrics** that test whether verification is actually working (M1 citation fidelity, M2 cascade coverage) live in `14_evaluation_scaffold.md`. The verifier emits signals; the eval scaffold measures them.
- The **runs observability** (log correlation by `run_id`, `alexandria logs show <run_id>`, `alexandria runs show <run_id>`) lives in `17_observability.md`. The runs table is the source of truth; the log stream surfaces it.

## Summary

Every wiki write is a staged run. Every run passes through a hostile verifier before commit. The verifier is fresh-context, read-only, and hostile-prompted. Verbatim quote anchors give the verifier a cheap deterministic check against citation fabrication. The run state machine has exactly five states and three terminal verdicts. Cascade transactions, synthesis envelopes, and budget-stop rollbacks are all the same mechanism. Raw files are never touched by the guardian or the verifier. The live wiki is untouched until the run reaches the `committed` verdict. DRY, SOLID, KISS.

This doc is the single answer to the ai-engineer's "the system cannot tell when it's wrong" concern. Everything downstream (evaluation in doc 14, cascade policy in doc 15, ops in doc 16) builds on it.
