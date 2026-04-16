# 14 — Evaluation Scaffold

> **Cites:** `research/reviews/03_ai_engineer.md` (§4, R4, R8, §3.6, §3.8), `13_hostile_verifier.md` (shares the verifier agent).

## The problem this doc closes

> *"There is no evaluation scaffold at all — no benchmark, no regression suite, no 'did the wiki get better or worse after this cascade' signal — which means the system will accumulate silent quality debt that no one can see until a retroactive query six months in returns something incoherent. The invariants are strong on intent but weak on falsifiability."* — `reviews/03_ai_engineer.md`, §1

The retroactive-query invariant (#15) is not testable today. "Features are judged on whether they make knowledge six months from now more queryable" is a principle without a proxy. This doc defines the **five proxies** that make the invariant testable, and the **`eval` operation** that runs them on a schedule.

Four design constraints from ai-engineer R4:

1. **Freeze new capabilities until M1 and M2 are running.** Evaluation is not a v2 feature.
2. **Reuse existing machinery.** The verifier agent from `13_hostile_verifier.md` is the measurement engine for M1, M2, and M5. No new agent runtime.
3. **Run as a fourth sibling to ingest/query/lint.** A new operation with the same tool-surface discipline — `eval` in the MCP layer, `llmwiki eval` on the CLI.
4. **Local-only.** No cloud benchmark service. All measurements happen on the user's machine against their own workspace.

## The five metrics

From ai-engineer §4, adopted verbatim with concrete thresholds.

### M1 — Citation fidelity

**Question:** when the wiki says *"X happened on date Y"* with a footnote `[^1]: source.pdf, p.3`, does page 3 of source.pdf actually say so?

**How it is measured:**

1. Sample 50 random claims from the wiki (stratified by topic directory).
2. For each claim, spawn a fresh **M1 verifier run** — same verifier runtime as `13_hostile_verifier.md`, prompted to vote on one specific claim against its cited span.
3. Votes: `supports` | `partially_supports` | `does_not_support` | `source_missing`.
4. Metric: `M1 = supports / (supports + partially_supports + does_not_support + source_missing)`.

**Thresholds:**

| Value | Meaning | Action |
|---|---|---|
| `M1 ≥ 0.95` | Healthy | No action. |
| `0.85 ≤ M1 < 0.95` | Degraded | Surface in `llmwiki status`, log a warning. Scheduled synthesis continues. |
| `M1 < 0.85` | Broken | Block scheduled synthesis. Require manual `llmwiki eval ack M1` to unblock. |

**Why 50.** Sampling enough claims to produce a stable percentage on a weekly cadence without blowing the verifier budget. At 50 claims × verifier cost-per-claim, M1 runs in roughly 10-20 kTok of inference weekly per workspace.

### M2 — Cascade coverage

**Question:** when a new source introduces a term, does every existing wiki page mentioning that term actually get touched by the cascade?

**How it is measured:**

1. For each ingest run committed in the last 7 days, pull the list of key terms from the source (top 20 by TF-IDF against the workspace's raw corpus).
2. `grep` each term across the wiki at the ingest's commit point.
3. Compare the grep result with the cascade's `touched_pages` from the run's plan.json.
4. Metric: `M2 = |touched_pages ∩ grep_matches| / |grep_matches|`.

**Thresholds:**

| Value | Meaning | Action |
|---|---|---|
| `M2 ≥ 0.90` | Healthy | No action. |
| `0.70 ≤ M2 < 0.90` | Degraded | Surface in status. Schedule a `lint --cascade-backfill` run. |
| `M2 < 0.70` | Broken | Block new ingests (not just synthesis — ingests too). `llmwiki ingest` errors with a pointer to `llmwiki eval report M2`. |

M2 is deterministic — no LLM is needed to compute it, just grep and set membership. This makes it the cheapest metric and the one that runs on **every ingest**, not just weekly.

### M3 — Retroactive query benchmark

**Question:** can the wiki answer the same question today that it answered last month? Does the answer get better or worse over time?

**How it is measured:**

1. Users seed a **gold standard** of 30 retroactive queries per workspace via `llmwiki eval gold add`. Each gold entry is `{query, expected_answer_topics, expected_citations, authored_at}`.
2. Monthly, the eval scaffold runs each gold query through the query workflow from `04_guardian_agent.md` — same tool surface, same agent loop, same model preset.
3. For each run, measure:
   - **Tool-call count** (how many primitives the agent needed).
   - **Answer-topic overlap** with `expected_answer_topics` (Jaccard on a topic set).
   - **Citation overlap** with `expected_citations` (set membership).
4. Metric: `M3 = mean(answer_topic_overlap) × mean(citation_overlap)`.

**Thresholds:**

| Value | Meaning | Action |
|---|---|---|
| `M3 ≥ 0.80 and stable or rising` | Healthy | No action. |
| `M3 stable or rising but < 0.80` | Never healthy, not regressing | Review gold standard — may need update. |
| `M3 declining month-over-month by > 0.05` | Regression | Block scheduled synthesis until reviewed. |

M3 is the most expensive metric — it runs a full query workflow 30 times. Runs monthly, not weekly. Costs ~50 kTok per run.

### M4 — Cost characterization

**Question:** is the compile-at-write-time bet actually cheaper than on-the-fly synthesis? When is the crossover week?

**How it is measured:**

1. Every LLM call via the daemon-owned agent loop logs to `llm-usage.jsonl` with `{run_type, workspace, tokens_in, tokens_out, cache_read, cache_write, usd}`. (Already in `11_inference_endpoint.md`.)
2. M4 aggregates per workspace:
   - `ingest_cumulative_tokens` — all ingest + cascade + verifier tokens per workspace since day 1.
   - `query_cumulative_tokens` — all query + verifier (for archive runs) tokens.
   - `hypothetical_on_the_fly_tokens` — an estimate of what a query-only system would spend: average tokens per query × number of queries × raw-corpus token count.
3. Metric: `M4_crossover_week` = the week at which `ingest_cumulative_tokens < hypothetical_on_the_fly_tokens`.

M4 is not a pass/fail metric. It is a **published number** per workspace in `llmwiki eval report`. Users with a negative crossover (ingest cost never pays off) know to reduce cascade scope or move to query-only mode.

This directly answers the cost model question from ai-engineer §3.8 and R6.

### M5 — Wiki self-consistency

**Question:** do different pages in the wiki agree with each other about the same topic?

**How it is measured:**

1. Sample 20 topics from `wiki/index.md`.
2. For each topic, find all wiki pages that mention it (grep + filter).
3. For each pair of pages mentioning the topic, extract claims specifically about that topic (via the verifier runtime, prompted to list claims per page).
4. Run a fresh verifier with a hostile prompt: *"Given these two sets of claims about topic T, find any contradictions. Return supports | independent | partial_contradiction | direct_contradiction for each claim pair."*
5. Metric: `M5 = (supports + independent) / all_pairs`.

**Thresholds:**

| Value | Meaning | Action |
|---|---|---|
| `M5 ≥ 0.95` | Healthy | No action. |
| `0.85 ≤ M5 < 0.95` | Mild drift | Surface top contradictions in `llmwiki status`. |
| `M5 < 0.85` | Significant drift | Block new ingests. Suggest `llmwiki lint --resolve-contradictions`. |

M5 catches the "wiki becomes a graveyard" failure mode — it rises when cascade is missing contradictions. Combined with M2 (cascade coverage), M5 is the **early warning** for knowledge decay.

## The `eval` operation

Alongside `ingest`, `query`, and `lint`, there is now a fourth operation. Same workflow discipline:

- **Runs as a staged run** with `run_type = 'eval'` in the runs table. Eval runs do not write to `wiki/`; they only append to `wiki/log.md` (a structural exception already allowed by `13_hostile_verifier.md`) and to the eval tables in SQLite.
- **Budget-bounded** via `[llm.budgets.eval]` in `11_inference_endpoint.md`.
- **Uses the same verifier runtime** as the hostile verifier — no separate agent architecture. DRY.
- **Runs on the daemon's scheduler** weekly by default (monthly for M3), or manually via `llmwiki eval run`.

### Storage

Two new tables (in `06_data_model.md`):

```sql
CREATE TABLE eval_runs (
  run_id       TEXT PRIMARY KEY REFERENCES runs(run_id),
  workspace    TEXT NOT NULL REFERENCES workspaces(slug),
  metric       TEXT NOT NULL,        -- 'M1'|'M2'|'M3'|'M4'|'M5'
  run_at       TEXT NOT NULL,
  score        REAL,                 -- the numeric metric value
  status       TEXT NOT NULL,        -- 'healthy'|'degraded'|'broken'
  tokens_used  INTEGER DEFAULT 0,
  usd_used     REAL DEFAULT 0,
  details      TEXT                  -- JSON: per-sample findings
);

CREATE INDEX idx_eval_runs_workspace_metric ON eval_runs(workspace, metric, run_at DESC);

CREATE TABLE eval_gold_queries (
  id           TEXT PRIMARY KEY,
  workspace    TEXT NOT NULL REFERENCES workspaces(slug),
  query        TEXT NOT NULL,
  expected_topics TEXT NOT NULL,     -- JSON array
  expected_citations TEXT NOT NULL,  -- JSON array of raw file paths
  authored_at  TEXT NOT NULL,
  authored_by  TEXT NOT NULL,        -- 'user' or 'auto'
  UNIQUE(workspace, query)
);
```

The gold query table is per-workspace and user-maintained. `llmwiki eval gold add` prompts the user to author a query + expected result. `llmwiki eval gold import <file>` imports from a YAML.

### CLI

```
llmwiki eval run [--metric M1|M2|M3|M4|M5|all] [--workspace X]
llmwiki eval report [--since 30d] [--workspace X]
llmwiki eval gold add [--query ... --topics ... --citations ...]
llmwiki eval gold list [--workspace X]
llmwiki eval gold import <file>
llmwiki eval ack <metric> [--reason "..."]    # acknowledge a broken metric to unblock
llmwiki eval floor --preset <preset>          # capability floor test (see below)
```

### MCP tool

One new tool exposed to agents:

| Tool | Purpose |
|---|---|
| `eval` | Run or report on the evaluation scaffold. Parameters: `metric`, `since`, `action=run|report`. Read-only from the agent's perspective (triggers a daemon job, does not modify wiki). |

The agent can ask *"what is the current health of workspace X's wiki?"* and get M1-M5 scores back. This is the measurement surface for the retroactive-query invariant.

## Capability floor (ai-engineer R8)

**Question:** what is the weakest LLM that can still run llmwiki's ingest workflow without silent failure?

**How it is measured:**

1. `llmwiki eval floor --preset <preset>` runs the following sealed test:
   - 10 curated source documents (shipped in `tests/fixtures/floor/`)
   - 1 synthetic workspace
   - Full ingest workflow using the named preset
   - Run M1 and M2 against the resulting wiki
2. Publishes:
   - `M1 score`
   - `M2 score`
   - `tool_call_count` (how many MCP tool calls the agent made per ingest — weaker models tend to use more)
   - `verdict`: `supported` (M1 ≥ 0.95, M2 ≥ 0.90), `degraded` (M1 ≥ 0.85, M2 ≥ 0.80), `unsupported`
3. Writes the result to `~/.llmwiki/state/floor-<preset>.json`.

**Startup warning:** when the daemon starts with a preset whose floor score is `degraded` or `unsupported`, or whose floor test has not been run, it logs a warning and writes to `llmwiki status`. The daemon still starts — no blocking — but the user knows their configured model is at or below the floor.

This closes ai-engineer R8 and §3.7 (the caller-model dependency). The floor is measurable, per-preset, and the user can make an informed choice.

## Freeze clause (Path A principle)

Per ai-engineer R4: *"Freeze new ingest sources until M1 and M2 are wired up and producing weekly reports."*

**Adopted.** Concretely:

1. **M1 and M2 must be running and writing to `eval_runs` before any new source adapter is added** beyond the ones documented in `05_source_integrations.md`, `09_subscriptions_and_feeds.md`, `10_event_streams.md`, and `12_conversation_capture.md`.
2. **M1 and M2 scores must be healthy on the shipped adapters before scheduled automatic synthesis is enabled** for any workspace. The hostile verifier from `13_hostile_verifier.md` runs per-ingest; the M1/M2 signal tells us whether the verifier is doing its job.
3. **A broken M1 or M2 blocks scheduled synthesis** via the status field thresholds above. Users can manually `llmwiki eval ack` to unblock if they understand the risk.
4. **M3 runs monthly** and its gold standard grows with the workspace. New gold queries are encouraged but not mandated.
5. **M4 is informational** — it never blocks, but its output is published in `llmwiki status` so users can see the cost curve.
6. **M5 is a warning signal** — degraded surfaces, broken blocks ingests to prevent contradiction compounding.

## SOLID application

- **Single Responsibility.** Each metric is a self-contained computation. `M1Metric`, `M2Metric`, `M3Metric`, `M4Metric`, `M5Metric` each implement the same `Metric` protocol. No metric touches wiki state directly — they only read and record.
- **Open/Closed.** Adding M6 (e.g., "time-to-answer regression") is a new class, not a modification. The scheduler discovers metrics via a registry.
- **Liskov.** Every metric returns the same `MetricResult` shape. Reporters and dashboards handle them uniformly.
- **Interface Segregation.** The `Metric` protocol has one method: `async def compute(workspace: str) -> MetricResult`. The runner knows how to schedule, bound the budget, persist the result. Metrics do not know about scheduling or persistence.
- **Dependency Inversion.** Metrics consume the verifier runtime via an injected `Verifier` instance, the raw filesystem via an injected `WorkspaceReader`, SQLite via an injected `ScopedDB`. Unit-testable without a real workspace.

## DRY notes

- **One verifier runtime** serves the hostile verifier (`13_hostile_verifier.md`), M1, and M5. The verifier is an agent loop; the difference between "verify this write" and "evaluate this claim" is a prompt, not a codebase.
- **One runs table** tracks verifier runs, eval runs, and synthesis runs. Different `run_type`, same state machine.
- **One log stream** (`~/.llmwiki/logs/llm-usage-YYYY-MM-DD.jsonl`) captures all LLM calls regardless of who made them. M4 rolls it up; no new instrumentation.

## KISS notes

- No new agent architecture. No new retrieval strategy. No cloud benchmark service. No new query language.
- Metrics are boring — grep, SHA-256, set membership, and an LLM vote. The LLM vote uses the verifier prompt unchanged.
- Thresholds are simple numeric cuts. No weighted scoring, no multi-dimensional traffic lights.

## Worked example — week 12 of a research workspace

```
$ llmwiki eval report --workspace research --since 30d

Workspace: research
Eval runs in the last 30 days:

M1  citation fidelity       0.97  (healthy)   last run 2026-04-14
M2  cascade coverage        0.93  (healthy)   last run 2026-04-16
M3  retroactive benchmark   0.84  (healthy)   last run 2026-04-01, next 2026-05-01
M4  cost crossover          week 19 (est.)    last updated 2026-04-16
M5  self-consistency        0.96  (healthy)   last run 2026-04-14

All metrics healthy. Scheduled synthesis enabled.

Trend (last 4 weeks):
  M1: 0.96 → 0.97 → 0.97 → 0.97
  M2: 0.91 → 0.93 → 0.94 → 0.93
  M5: 0.95 → 0.96 → 0.96 → 0.96
```

When a metric breaks:

```
$ llmwiki eval report --workspace research

M1 citation fidelity  0.81 (BROKEN)  last run 2026-04-15
  → scheduled synthesis is BLOCKED
  → run `llmwiki eval report M1 --details` to see failing claims
  → override with `llmwiki eval ack M1 --reason "..."` if you know why
```

The user has a clear signal, a clear action, and a clear path to unblock.

## What this doc does NOT cover

- The **verifier runtime itself** — defined in `13_hostile_verifier.md`. Metrics consume it.
- The **runs state machine** — also `13_hostile_verifier.md`. Eval runs are just `run_type = 'eval'`.
- The **cost model** that M4 measures — the budgeting, accounting, and telemetry are in `11_inference_endpoint.md`.
- The **dashboards and `llmwiki status` formatting** — that lives in `17_observability.md`. This doc writes the rows; observability shows them.

## Summary

Five metrics. One operation (`eval`). Shared verifier runtime. Freeze clause adopted. Capability floor is measurable. Retroactive-query invariant is testable via M3. Every concern the ai-engineer raised in §4 has a number it reports and a threshold it enforces.

This is the measurement surface. The next time someone asks *"is llmwiki working?"*, the answer is `llmwiki eval report`.
