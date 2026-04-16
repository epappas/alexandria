# Plan Review: AI Engineer

**Reviewer:** ai-engineer specialist agent
**Date:** 2026-04-16
**Artifact under review:** `docs/IMPLEMENTATION_PLAN.md` (draft v1, 13 phases, before any code is written)
**Round:** 1 (plan review). The architecture review is in `../03_ai_engineer.md`.

**Note on scope:** A first attempt at this review timed out after a single tool call without producing output. This is the second invocation, with the same prompt plus a tightened deliverable instruction. The other two reviewers' findings were summarized in the briefing so the AI-engineering perspective could focus on what's invisible from the LLM-architecture and MLOps angles.

---

## Executive take

The plan honors R1, R2, R3, R5, R6, R7, and R8 in letter and substantially in spirit. R4 is the one that has been quietly reinterpreted, and the reinterpretation is defensible but needs to be made explicit and load-bearing. Phase 2 ships the verifier (V0+V1) before any belief layer exists, and Phase 3 adds beliefs on top — this ordering creates a real integrity gap that the plan does not currently acknowledge. I agree with llm-architect that Phase 2 is under-sized and with mlops-engineer that the ops debt window is dangerous; I am not going to repeat those points. My findings are about the things that only show up when you stare at the AI quality story end-to-end.

## The R4 freeze clause question

**The plan reinterprets R4 rather than honoring it as originally written.**

Original R4 said: freeze new ingest sources until M1+M2 are wired and producing weekly reports. The plain reading is "no new sources before M1+M2." The plan defers M1+M2 to Phase 9 and ships sources in Phases 1 and 4 (web_html, rss, markdown_dir, github) — three months earlier. The plan justifies this with "freeze applies to new sources beyond the documented MVP set, not to the MVP set itself."

This is a softening, but it is a defensible softening if and only if the MVP set is **frozen in writing now and treated as a hard ceiling**. The plan does this in the source-set commitment and at the R8 capability floor — good. What is missing: **a written commitment that any source added between Phase 4 and Phase 9 is treated as a R4 violation, not as a "small addition."** The lived failure mode of freeze clauses is exactly this: the team adds "just one more, it's small, it's basically the same as RSS" and the freeze evaporates by attrition.

The plan should not be allowed to ship Phase 4 without the freeze ceiling being a phase exit criterion that the three-agent review explicitly verifies. Right now it is a top-level principle but not a phase gate.

**Verdict:** the reinterpretation is acceptable, but it needs teeth. As written, R4 is honored as an aspiration, not as an enforcement.

## Top three findings

### 1. **BLOCKER — Phase 2 wiki content is written without belief sidecars and Phase 3 does not retroactively backfill them**

Phase 2 ships the verifier and writes wiki pages with "claim → citation" maps. Phase 3 introduces the belief layer with `belief.id`, `valid_from`, `valid_to`, and the `current` flag. Phase 9 wires M1, which samples random *current beliefs* and verifies their citations.

The problem: Phase 2's wiki pages have citations but no beliefs. When Phase 3 lands, what happens to those Phase-2-era citations? The plan is silent. There are three possible outcomes and the plan needs to commit to one in writing:

(a) **Backfill on Phase 3 migration**: every Phase 2 citation becomes a belief retroactively, with `valid_from = original_write_time`. This is the only option consistent with R4 and M1 sampling integrity, and it requires a documented migration in Phase 3's acceptance criteria.

(b) **Orphaned outside M1**: Phase 2 content stays as "pre-belief" and is excluded from M1 sampling. This breaks M1 because the sample is no longer representative — exactly the content the verifier was weakest on (V0+V1 only) is the content M1 will never measure.

(c) **Re-verified at Phase 3**: every Phase 2 wiki page is re-run through the verifier with the new belief layer attached. Expensive but honest.

Phase 3's acceptance criteria currently say "belief table populated from existing wiki content" without specifying which option. **This must be resolved before Phase 2 ships any wiki content**, because the answer changes Phase 2's data model. If (a) is chosen, Phase 2 needs to write citations in a shape that Phase 3 can lift into beliefs without an information-losing transform.

### 2. **BLOCKER — The cascade convergence test is missing from Phase 2 acceptance even though the policy ships in Phase 2**

The plan correctly puts the cascade convergence policy ("hedge with dated marker, never silently overwrite") in Phase 2 alongside the verifier. Phase 2's tests include "ingest two contradicting RSS items, observe two beliefs created at different times, observe wiki page hedging." But beliefs do not exist until Phase 3. The test as written cannot run in Phase 2.

This is not a cosmetic ordering bug — it means the convergence policy ships in Phase 2 without a test that proves it works. The failure mode is exactly the one R5 was meant to prevent: silent overwrite. Without a Phase 2 test that ingests two contradicting sources and asserts the wiki hedges them rather than overwriting, R5 is an unverified architectural promise.

The Phase 2 test should be rewritten to be belief-free: ingest source A asserting X, ingest source B asserting not-X, assert that the wiki page contains both claims with separate citations and a hedge marker, and that neither claim was deleted. This test must be deterministic and must pass before Phase 2 closes.

### 3. **IMPORTANT — Verifier evasion rate is not measured in Phase 2, so verifier softening will not be detectable**

llm-architect is right that schedule pressure will compromise verifier strictness. My prior R1 review listed "verifier evasion rate" as a tracked metric. The plan does not include it as a Phase 2 acceptance criterion. The plan tests "verifier catches a fabricated citation hash" — that is a single deterministic test, which only catches the shallowest form of fabrication (hash mismatch). It does not catch the harder fabrications: cherry-picked quotes that are technically present but wrenched from context, claims that paraphrase a source while changing the meaning, attribution of a quote to the wrong source.

Phase 2 needs a small adversarial corpus — 20-30 hand-built fabrication test cases at varying difficulty — with the verifier's catch rate as a tracked number. Below a threshold (say 90% on the tier-1 deterministic cases, 70% on the tier-2 LLM-judged cases), Phase 2 cannot close. Without this, the verifier is shipped without a fitness function, and the only way to detect softening is in production.

This corpus doubles as the Phase 2-to-Phase 9 bridge: the same corpus becomes part of M3 (verifier evasion) when M3 lights up.

## The single biggest AI-engineering risk

**The plan ships the verifier in Phase 2 and then waits 6 phases (~5 months) before the evaluation scaffold lights up to measure whether the verifier is actually working.** During that window, the verifier's quality is asserted by its existence, not by any number. If the verifier is too strict it blocks legitimate writes and the user works around it by lowering thresholds in config — invisible. If it is too loose it admits fabrications and the wiki silently degrades — also invisible. Both failure modes look identical from the outside (the system "works") and both are the exact thing R1 and R4 were meant to prevent. The five months between "verifier ships" and "we can measure the verifier" is the period during which the architecture's central trust mechanism operates on faith, and there is no plan to bridge that gap with even an interim metric.

This is invisible to llm-architect (whose concern is Phase 2 sizing) and invisible to mlops-engineer (whose concern is Phase 4-11 ops debt). It is the AI-engineering blind spot none of the other two reviewers will catch.

## Three concrete recommendations

1. **Move M3 (verifier evasion rate) earlier — into Phase 2 itself, not Phase 9.** M3 is the only metric that does not depend on the belief layer; it can run against the verifier in isolation with the adversarial corpus. Shipping a stripped-down M3 in Phase 2 closes the five-month measurement gap and gives the three-agent review at the end of Phase 2 something concrete to sign off on. M1 and M2 stay in Phase 9 because they need beliefs.

2. **Add a Phase 3 migration spec for backfilling Phase 2 citations into beliefs.** Pick option (a) from finding 1, write the migration in Phase 3's acceptance criteria, and constrain Phase 2's citation schema to be lift-compatible. Ship Phase 2 only after the lift transform is specified on paper. This is finding 1 made executable.

3. **Make the R4 source ceiling a Phase 4 exit criterion that the three-agent review must explicitly check.** Add this line to Phase 4 acceptance: "Three-agent review verifies that the MVP source set is unchanged from the line 73 list and that no proposals to extend it have been silently merged." This is the teeth that the freeze clause currently lacks.
