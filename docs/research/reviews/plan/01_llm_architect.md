# Plan Review: LLM Architect

**Reviewer:** llm-architect specialist agent
**Date:** 2026-04-16
**Artifact under review:** `docs/IMPLEMENTATION_PLAN.md` (draft v1, 13 phases, before any code is written)
**Round:** 1 (plan review). The architecture review is in `../01_llm_architect.md`.

---

## 1. Executive Take

The plan is structurally sound and demonstrates genuine discipline around the three hardest problems in this class of system: staged writes, hostile verification, and honest budget enforcement. The phase sequencing has internal logic — verifier before sources, sources before subscriptions, subscriptions before scheduled synthesis — and the decision to front-load Phase 2 with the verifier cascade is correct because nothing downstream can be trusted until that load-bearing component exists. The plan also resists the common temptation to build a generic LLM abstraction before a single real call has been made. That instinct serves it well.

However, the plan underestimates Phase 2 badly and splits the caching strategy in a way that will actively burn tokens during the inner development loop of Phase 2 itself. The biggest LLM-architectural concern is not any single missing feature — it's that the verifier cascade, the staged-write envelope, verbatim anchor extraction, provider abstraction, budget enforcement, and tests against real Anthropic API all land in one phase, and the failure mode of under-sizing Phase 2 is not "Phase 2 slips by a week" — it's that the team will be tempted to compromise the verifier's strictness to ship, and the verifier is the one component that cannot be compromised without falsifying the entire product's core claim. Once the verifier is softened, every downstream phase is building on sand.

## 2. Specific Findings

### Finding 1: Phase 2 scope is ~40% over realistic capacity — **BLOCKER**

Phase 2 at 2.5 weeks contains: staged-write transactional envelope, verbatim quote anchor extraction + hashing, verifier protocol + default implementation, cascade workflow (strict → advisory → manual), minimum viable Anthropic provider, `alexandria ingest` end-to-end wiring, and tests that include live Anthropic API calls with a real budget. Each of those, done properly, is a 2-4 day unit of work for a careful engineer. The verifier alone — because it must handle hallucinated quotes, partial matches, whitespace normalization, unicode edge cases, and the escalation cascade — is easily a week. The staged-write envelope has its own 3-4 day footprint because it has to be idempotent, rollback-safe, and survive process crashes mid-write. The Anthropic provider minimum viable product is deceptively small but needs streaming, error taxonomy (rate limit vs auth vs content policy vs transport), retry policy, and budget hooks. Adding 2-3 days for tests against the real API (each iteration of which costs real money and clock time, not just compute). Realistic sizing is 4 weeks if the team is sharp and has done this before, 5 weeks otherwise.

### Finding 2: Prompt caching must land with the verifier, not in Phase 8 — **BLOCKER**

Anthropic prompt caching is not an optimization — for this workload it's a cost governance mechanism. The verifier's system prompt (containing verification rules, output schema, edge case handling) is going to be 1500-3000 tokens, and it will be sent on every verification call. During Phase 2's inner development loop, the team will run the verifier hundreds of times against recorded test fixtures. Without `cache_control` on the system prompt, each run burns full input-token costs. With caching, the cached portion drops to ~10% of standard cost after the first call and stays cached for 5 minutes. Over the course of Phase 2 development and testing, the delta is easily $50-200 in wasted spend, but the more important effect is psychological: the team will start rationing their verifier tests to save money, which degrades the very component that most needs rigorous exercise. Caching must be implemented as part of the minimum viable Anthropic provider in Phase 2, not deferred.

### Finding 3: Budget enforcement split creates a real runaway risk in Phase 2 — **IMPORTANT**

The plan implements "basic" budget enforcement in Phase 2 and "full" enforcement with verifier multiplier and per-preset routing in Phase 8. The problem: the verifier multiplier exists precisely because verification calls are issued per-quote, and a synthesis run that extracts 40 quotes issues 40+ verification calls. A user running Phase 2 `alexandria ingest` against a workspace with 100 sources, with a daily budget set assuming one verification per source, can easily hit 10x the expected spend in a single run. The basic enforcement must at minimum include: (a) the verifier multiplier as a config value even if not automated, (b) a hard per-run ceiling that aborts before the N+1st call if spend exceeds a configured cap, (c) a pre-flight cost estimator that warns before starting runs above a threshold. Without these, the first real workspace run in Phase 2 is a credit card incident waiting to happen.

### Finding 4: Phase 1 `guide` tool has no honest L1 content to emit — **IMPORTANT**

The L0/L1 tiered guide structure is correct and the decision to ship it in Phase 1 is correct — but Phase 1 has no runs, no verifier, no eval metrics. The failure mode is that `guide` emits empty sections for "recent runs", "verifier verdicts", "eval health" and the user / caller agent cannot distinguish "this system is broken" from "this system has not yet been used". The fix is explicit: those sections must emit a structured "not yet populated — first run expected after Phase N" message, not empty strings, not null, not silent omission. Better yet, the Phase 1 guide should include a "phase" field declaring which capabilities are wired and which are dormant, so a connected agent can read that field and adjust its own behavior. This is a small correction but it touches the plan's no-lies invariant directly.

### Finding 5: The freeze clause vs. Phase 4/5 source work is a wording problem, not a plan conflict — **NICE-TO-HAVE**

The `14_evaluation_scaffold.md` freeze clause should be read as "no new source types or schemas beyond the documented MVP set until M1+M2 ship against the capability floor fixture." Phase 4 and Phase 5 implement source types that are already documented in the MVP, so they are not net-new sources in the sense the freeze clause means. But this interpretation is not stated in the plan. A one-paragraph clarification in Phase 4's opening — "the freeze clause permits MVP-documented source types; it prohibits adding source types not in the architecture set" — closes the ambiguity and prevents a reviewer from flagging it every time.

### Finding 6: Multi-provider + scheduled synthesis + full budget in Phase 8 is a single-phase monolith — **IMPORTANT**

Phase 8 at 2.5 weeks contains: OpenAI provider, OpenAI-compatible provider (local models via vLLM / llama.cpp / Ollama), scheduled synthesis runtime, full `llm/budget.py` with per-preset routing and verifier multiplier, prompt caching (if it survives Phase 2), and integration tests against a second provider. This is two phases: one for multi-provider abstraction with budget completion, one for scheduled synthesis. Scheduled synthesis is a substantial piece — it's a background runtime with cron parsing, durable job state, crash recovery, budget pre-flight checks per run, and verifier integration. Combining it with provider work means a slip in either half derails both.

### Finding 7: Test LLM costs need a per-run ceiling, not just a budget — **IMPORTANT**

Real Anthropic API tests in CI with a small budget sounds safe until a malformed test fixture produces a 100K-token response loop and burns the daily CI allowance in a single PR. The monthly LLM cost for a conservatively designed test suite — 50 tests issuing 2-5 verifier calls each, running ~20 times per PR week at ~5 PRs per week — is realistically $30-80/month with prompt caching, $100-300/month without it. The dominant risk is not the expected cost but the tail: one runaway loop can 10x a week's spend. CI needs (a) a hard per-test timeout that kills the process at 30s, (b) a hard per-test token ceiling that aborts mid-stream at 10K output tokens, (c) a CI-specific provider config that sets `strict_budget_mode = hard_fail`. A single budget number is not enough.

### Finding 8: `13_hostile_verifier.md` coverage is good but anchor-format versioning is missing — **IMPORTANT**

The plan covers the verifier protocol, the cascade, and staged writes — good. What it does not explicitly cover: the anchor format must be versioned from day one. If the team ships v0 anchor format in Phase 2 and discovers in Phase 9 that normalized quotes need unicode NFC, or that whitespace collapsing needs to be semantic-aware, re-anchoring an existing wiki is a migration nightmare. The verifier's anchor storage must include a `schema_version` field so migrations can be targeted and staged. This is a 2-hour add to Phase 2 that saves a week in Phase 9 or later. Flag it now.

### Finding 9: `14_evaluation_scaffold.md` capability floor needs a fixture checkpoint in Phase 2, not Phase 9 — **IMPORTANT**

The capability floor landing in Phase 9 alongside metrics is logical — you need metrics to measure against the floor. But the 10 curated sources themselves should be committed to the repo in Phase 2, even if the metric harness that runs against them lands later. The reason: during Phase 2's verifier development, the team needs a stable, realistic corpus to test against. Building verifier tests against throwaway fixtures and then swapping in the capability floor in Phase 9 means every Phase 2 test may need to be rewritten. Land the 10 sources in Phase 2, land the metric harness in Phase 9 — the sources themselves are a documentation artifact that doesn't depend on the metrics code.

### Finding 10: No explicit plan for verifier false-negative monitoring — **IMPORTANT**

The verifier can fail in two directions: false positive (accepts a hallucinated quote) and false negative (rejects a valid quote that happens to be formatted unusually — em-dash normalization, smart quotes, indentation). The plan discusses the cascade for handling rejections but does not discuss how false-negative rate is measured over time. If the verifier starts rejecting 30% of valid quotes, the user's trust in the product collapses even though the verifier is "working". Phase 9's eval metrics must include verifier false-negative rate as a tracked metric, sampled by the user spot-checking rejected quotes. This is explicit and should be called out in the plan.

## 3. The Most Underestimated Phase

**Phase 2 is most likely wrong at 2.5 weeks. Realistic sizing is 4-5 weeks.** Re-scope by splitting:

**Phase 2a (2 weeks): Verifier and staged writes.** Staged-write envelope, verbatim anchor extraction with versioned schema, verifier protocol with default strict implementation, cascade workflow. No LLM calls yet — the verifier in 2a operates on fixtures with pre-recorded LLM outputs. The capability floor 10 sources commit here.

**Phase 2b (2 weeks): MV Anthropic provider + live verification.** Minimum viable Anthropic provider with streaming, error taxonomy, retry, prompt caching from day one, budget hooks including verifier multiplier and per-run ceiling. `alexandria ingest` end-to-end wired through live Anthropic. Tests against live API with hard ceilings. Real budget smoke tests.

This split is not just scheduling hygiene — it isolates the expensive, real-money, slow-iteration work (2b) from the pure-logic work (2a), which means 2a can ship and be reviewed before any Anthropic budget is spent.

## 4. The Single Biggest Risk

**The verifier strictness will be compromised under Phase 2 schedule pressure.** Phase 2 is load-bearing and Phase 2 is under-sized. When a 2.5-week phase hits week 3 with the cascade workflow still buggy and the CI burning Anthropic credits, the rational-in-the-moment decision is to soften the strict tier's quote matching rules — accept whitespace-normalized matches, accept close-enough matches, accept advisory passes as strict passes. Each softening is individually defensible and each one silently invalidates the product's core claim that synthesized content is anchored to verbatim source. Once shipped, softened rules are nearly impossible to re-tighten without breaking every wiki page already written against them.

The specific mitigation: the verifier's strict-tier rules must be code-frozen at the end of Phase 2a (before any live API work), committed with their test fixtures, and any change to strict-tier rules in Phases 2b through 13 requires explicit documented justification and re-running the full capability floor. Make the strict tier hard to weaken, or it will be weakened.

## 5. Recommendations (Ranked)

1. **Split Phase 2 into 2a and 2b as described above.** This is the single highest-leverage change. It isolates deterministic logic from live-API work and adds review points before spending real budget.

2. **Move Anthropic prompt caching from Phase 8 into Phase 2b, mandatory in the minimum viable provider.** The system prompt of the verifier is the perfect cache candidate and the savings compound across the entire development cycle.

3. **Harden budget enforcement in Phase 2b with three explicit mechanisms: verifier multiplier, per-run ceiling, pre-flight cost estimator.** These cannot wait for Phase 8. Without them, the first real workspace run is a financial risk.

4. **Commit the 10 capability floor sources to the repo in Phase 2a.** The fixture is a documentation artifact, not a measurement artifact. Phase 9 adds the harness; Phase 2 adds the data.

5. **Version the verifier anchor schema from the first commit.** Two hours of work, saves a migration in a later phase.

6. **Add a per-test CI ceiling on token output and wall time, plus a CI-specific strict budget mode.** A single budget number is insufficient — the tail case of a runaway response must be killed at 10K tokens or 30 seconds, whichever comes first.

7. **Split Phase 8 into two phases: multi-provider + budget completion, then scheduled synthesis.** Scheduled synthesis is a background runtime with crash recovery concerns that deserves its own review cycle.

8. **Clarify the Phase 1 `guide` tool's behavior for unpopulated L1 fields** — structured "not yet populated" messages with a phase indicator, not empty strings.

9. **Add verifier false-negative rate as a tracked metric in Phase 9's eval set.** The verifier can fail silently by rejecting valid quotes; this must be measured.

10. **Add a one-paragraph clarification in Phase 4 about the freeze clause scope.** Prevents repeated reviewer confusion without changing any code.

The plan is well-intentioned and the foundation is correct. The corrections above are not a rejection of the plan — they are the difference between a plan that survives first contact with real Anthropic API traffic and a plan that slips badly in Phase 2 and then compromises the verifier to recover schedule. Approve the plan after incorporating findings 1-3 at minimum. The remaining findings can be tracked as plan amendments during Phase 1.
