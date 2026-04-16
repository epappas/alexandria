# Implementation Plan Reviews

Independent reviews of the **alexandria implementation plan** (`docs/IMPLEMENTATION_PLAN.md`) by three specialist agents, conducted before any code is written. This is the **first checkpoint** — the plan itself is the artifact under review.

The earlier round of reviews (`docs/research/reviews/01_*` through `03_*`) covered the **architecture**. This round covers the **plan to build it**. After each implementation phase ships, the same three agents will review the actual deliverables (the per-phase reviews will land in numbered subdirectories `phase00/`, `phase01/`, etc.).

| # | Reviewer | Status | Biggest finding |
|---|---|---|---|
| [01](01_llm_architect.md) | llm-architect | Complete | **Phase 2 is ~40% under-sized**; the verifier strictness will be compromised under schedule pressure if Phase 2 is not split into 2a (deterministic logic) and 2b (live API). Prompt caching must land in Phase 2b, not Phase 8. |
| [02](02_ai_engineer.md) | ai-engineer | Complete (second-attempt invocation; first attempt timed out) | **Phase 3 belief migration must be specified before Phase 2 ships wiki content.** Phase 2 writes citations without beliefs; Phase 3 adds beliefs; the lift transform must be designed up front, not after the fact. M3 (verifier evasion rate) must move from Phase 9 to Phase 2 to bridge the 5-month measurement gap. The plan reinterprets R4 (freeze clause) defensibly but needs explicit teeth — make it a Phase 4 exit criterion. |
| [03](03_mlops_engineer.md) | mlops-engineer | Complete | **Secret rotation + log redaction must move from Phase 11 to Phase 4** — the 5-month "ops debt window" of running real GitHub PATs without rotation, revocation, or log redaction is the single biggest risk in the plan. Backup, FTS5 integrity check, and crash dumps all need to move into Phase 0. |

## Convergent findings (flagged by 2+ reviewers)

1. **The plan defers too many ops/correctness primitives to the wrong phases.** llm-architect wants prompt caching in Phase 2 (currently Phase 8); mlops-engineer wants secret rotation, log redaction, backup, FTS integrity, and crash dumps in earlier phases (currently Phase 11). Both reviewers see the same pattern — load-bearing primitives are scheduled too late and create gaps where users are exposed.
2. **Phase 2 is the highest-stakes phase and is almost certainly under-sized.** llm-architect explicitly says 40% over realistic capacity and recommends splitting into 2a/2b. mlops-engineer indirectly agrees by recommending Phase 6 split into 6a/6b for similar reasons.
3. **The freeze-clause wording is ambiguous and needs explicit clarification in Phase 4.** Both reviewers flag the gap between Phase 4 (sources ship) and Phase 9 (eval gates them). The plan's interpretation ("freeze applies only to net-new sources beyond the MVP set") is defensible but not documented.

## Reading order

1. **mlops-engineer (`03_mlops_engineer.md`)** — start here because the secret-rotation finding is the single most acute risk and the fix is small (~150 lines of code in Phase 4).
2. **llm-architect (`01_llm_architect.md`)** — read second because the Phase 2 sizing argument is the most consequential structural change to the plan.
3. **ai-engineer (`02_ai_engineer.md`)** — read third when complete; the AI-engineering perspective ties the verifier-quality story together with the freeze clause and evaluation gating.

## What gets fixed before code starts

The reviews surface concrete blocker items. Before Phase 0 begins, the implementation plan must be amended to:

- Move secret rotation, revocation, audit log, and log redaction into Phase 4 alongside the basic vault.
- Move backup-create, FTS integrity check, and crash dumps into Phase 0.
- Split Phase 2 into 2a (deterministic verifier + cascade + staged writes) and 2b (live Anthropic + budget hardening + prompt caching).
- Split Phase 6 into 6a (single-child daemon) and 6b (multi-child + IPC).
- Add a Phase 4 self-report (weekly counts of ingests/errors/slowest runs) to bridge the freeze-clause gap until eval ships in Phase 9.
- Commit the 10 capability floor sources in Phase 2a; the metric harness still ships in Phase 9.
- Version the verifier anchor schema from the first commit.
- Add a CI-specific strict budget mode with per-test token ceilings and wall-time killers.

These are not nice-to-haves. They are the difference between a plan that survives Phase 2 and one that compromises the verifier under pressure.

## What this folder will look like over time

```
docs/research/reviews/
├── README.md                            (top-level — covers BOTH rounds)
├── 01_llm_architect.md                  (architecture review, round 1)
├── 02_ai_engineer.md                    (architecture review, round 1)
├── 03_mlops_engineer.md                 (architecture review, round 1)
└── plan/
    ├── README.md                        (this file — plan review round)
    ├── 01_llm_architect.md
    ├── 02_ai_engineer.md
    └── 03_mlops_engineer.md
```

After Phase 0 ships, `phase00/` joins the tree with the same three reviews. Same for every subsequent phase. The pattern: one review folder per checkpoint, three agents per folder.
