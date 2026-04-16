# Architecture Reviews

Independent reviews of the llmwiki architecture by three specialist agents, run 2026-04-16. Each reviewer was given the same documentation map, the existing invariants they were told not to re-litigate, and a specialty-specific question set. Each produced a full review independently; none of them saw the others' output.

The reviews are preserved verbatim so future architecture decisions can cite the original critiques (not my synthesis of them).

| # | Reviewer | Scope | Biggest finding |
|---|---|---|---|
| [01](01_llm_architect.md) | llm-architect | Tool surface, prompt caching, retrieval charter, LLM-application architecture | **Missing `overview` tool** — cold-start ergonomics cost 3-8 turns per session |
| [02](02_mlops_engineer.md) | mlops-engineer | Operations, reliability, schema evolution, observability, failure modes | **Failure isolation inside the daemon** — one process does scheduler + pollers + MCP + web UI; one crash takes everything down |
| [03](03_ai_engineer.md) | ai-engineer | System quality, workflow correctness, citation fidelity, cascade dynamics, evaluation | **No adversarial check on guardian output** — every correctness mechanism runs inside the same LLM context that did the write; and **no evaluation scaffold** |

## Reading order

1. **Start with `03_ai_engineer.md`** — the strongest review. The "loop walkthrough" scenario and the "single biggest gap" section together reframe the central risk: the guardian is its own only checker, and the architecture has no mechanism for knowing when it's wrong.
2. **Then `02_mlops_engineer.md`** — the most operationally grounded. Identifies concrete gaps around schema migrations, daemon supervision, rate limiting, and recovery that are practical blockers for production use.
3. **Finally `01_llm_architect.md`** — the most positive. Surface-level refinements to a sound core, most notably the missing `overview` tool.

## Convergent findings (flagged by 2+ reviewers independently)

1. **Scheduled synthesis crash / partial-write recovery.** Named by llm-architect §2.6 ("synthesis run envelope"), mlops #4 ("daemon supervision state machine"), and ai-engineer R3 ("formalize cascade as a transaction").
2. **No evaluation / no falsifiability.** ai-engineer §4 (proposes 5 metrics M1-M5), mlops #10 (observability insufficient for field debugging), llm-architect implicitly.
3. **Rate limiting / back-pressure / failure containment.** mlops #5, llm-architect hints in the daemon cache discussion.
4. **Citation enforcement is weak.** ai-engineer §3.1 ("syntactic, not semantic"), llm-architect implicitly (trust-in-caller assumption).
5. **Tool surface has gaps.** llm-architect §2.2 (`overview` missing), ai-engineer §3.2 (`str_replace` doesn't scale with cascade breadth).

## Unique-but-critical findings

- **llm-architect:** L0/L1 budget numbers vs Anthropic caching floors (4096 Opus / 2048 Sonnet); the docs conflate total-call and output budgets.
- **mlops-engineer:** Schema migrations framework is completely absent; first v2 change will brick installs.
- **ai-engineer:** Cascade convergence has no policy (what happens when paper N contradicts paper M?); the wiki shape becomes a function of ingest order.

## Notes on fidelity

Line references in the reviews are approximate. The reviewers had document access but did not consistently use a line-aware viewer, so line number citations should be treated as regional. The mlops review cites `08_config_and_secrets.md` which does not exist — our dedicated secrets doc is not written. The critique still applies to the de-facto secrets story scattered across other docs; treat it as identifying a missing doc, not a wrong citation.

The three reviews were dispatched on 2026-04-16 via parallel `Agent` tool calls. Each review took ~90-120 seconds of wall time. The raw reviews are the source of truth; my synthesis in chat is a condensation and may emphasize different things.
