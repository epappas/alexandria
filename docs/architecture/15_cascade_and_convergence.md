# 15 — Cascade and Convergence Policy

> **Cites:** `research/reviews/03_ai_engineer.md` (R5, §3.2), `13_hostile_verifier.md` (the staging mechanism that makes cascades atomic), `14_evaluation_scaffold.md` (M2 measures whether this policy holds).

## The problem this doc closes

> *"When paper 10 contradicts paper 3. The guardian has to decide whether to rewrite the claim, add a 'disputed' marker, or create a new sub-page. Nothing in doc 04 says what the right answer is ... over 50 papers you accumulate a page that either (a) silently converges on whichever view the last paper supported, or (b) becomes a dense thicket of hedges, or (c) fragments into a topic tree the user never asked for."* — `reviews/03_ai_engineer.md`, §2

Karpathy's pattern is famously vulnerable to the "wiki becomes a graveyard" failure mode where cascade updates fight over a shared page until its shape reflects ingest order rather than underlying knowledge. This doc defines **the one policy** the guardian must follow when a new source contradicts an existing claim, plus the workflow that enforces it through the staged-write transaction from `13_hostile_verifier.md`.

One rule. One workflow. No cleverness.

## The rule — hedge with dated markers

When source N introduces a claim that contradicts a claim from an earlier source M (where `M.collected_at < N.collected_at`), the guardian **MUST**:

1. **Preserve** the existing claim exactly as it is, with its original citation to M.
2. **Append** the new claim as a dated *"as of"* annotation, citing N.
3. **Mark** the section as `::: disputed` with a link to the other side.
4. **Record** the contradiction in `wiki/overview.md`'s *Contested claims* section.
5. **Record** a cross-link to any other page on the same topic so the disputed claim is discoverable from every angle.

The retroactive-query property — *"what did I think in April?"* — requires that the April claim still exists in April's form, with April's citation, and that the May update is identifiable as a May update. Overwriting loses history. Fragmenting into sub-pages loses the single-page-per-concept invariant. Silent hedging without dates loses the timeline. The dated-marker hedge is the only option that preserves all three properties.

### Canonical markdown shape

```markdown
## Token refresh in OAuth flow

::: disputed
The refresh token endpoint is at `/oauth/refresh`. [^1]

**Updated 2026-03-15 per RFC 0034 [^2]:** the endpoint was moved to
`/auth/v2/refresh` as part of the v2 migration. The `/oauth/refresh` path
still responds with a 301 redirect as of April 2026.

[^1]: acme-api-spec-v1.md, p.12 — *"Token refresh is served at the path `/oauth/refresh`."*
[^2]: acme-rfc-0034.md, p.3 — *"v2 moves the refresh endpoint to `/auth/v2/refresh`. The legacy path returns 301 until 2026-12."*
:::

See also: [acme-api-versioning](acme-api-versioning.md), [acme-rfc-0034](acme-rfc-0034.md).
```

Three conventions:

1. The `::: disputed` fenced admonition is parseable markdown (compatible with Obsidian, MkDocs Material, GitHub, etc.) and is what the guardian produces and the verifier checks.
2. The "Updated YYYY-MM-DD per <source>" pattern is a literal string the verifier grep'es for.
3. Citations must quote a **verbatim span** from each source — this is the quote-anchor requirement from `13_hostile_verifier.md`. The verifier's deterministic check catches fabricated quotes before the LLM is involved.

### When is something "contradicted" vs "superseded" vs "elaborated"

Three cases, one rule:

- **Contradicted** — two sources assert incompatible facts (different endpoint, different date, different actor). Apply the hedge policy above.
- **Superseded** — a newer source replaces an older one (v1 deprecated in favor of v2). Same policy; the dated marker carries the word "superseded" in the body but the structural shape is identical.
- **Elaborated** — a newer source adds detail without contradicting the original. **No hedge.** The existing claim is merged with the new one; the citation list grows; the section remains single-voice.

The verifier in `13_hostile_verifier.md` check #2 (per-run) decides the case. Elaborated claims pass through as normal merges. Contradicted and superseded claims must land under `::: disputed`. If the guardian writes a contradicted claim *without* the hedge, the verifier rejects the run.

## The cascade workflow (staged)

This is an expansion of the `04_guardian_agent.md` ingest workflow, applied specifically to the cascade phase. The transaction mechanism lives in `13_hostile_verifier.md`; this section describes what the guardian plans and stages **inside** that transaction.

### Phase 1 — Read and extract

The guardian reads the new source. For each non-trivial claim it finds:

1. Extract the claim text.
2. Extract the verbatim quote span from the source (for the quote anchor).
3. Tag the claim with candidate topics (from the existing wiki's index + any new topics the claim introduces).

No writes yet. The output is a `claims.json` file in the staging area.

### Phase 2 — Locate related pages

For each claim, `grep` the wiki for related content using:

1. Claim key terms (top TF-IDF tokens).
2. Topic tags.
3. Entity references from the claim.

Each match produces a tuple `(claim_id, page_path, match_spans, relation)` where `relation` is one of:

- `same_claim_to_merge` — the page already says something very close; new source supports it (elaboration case).
- `same_claim_contradicted` — the page says something incompatible; hedge required.
- `adjacent_topic` — the page discusses a related concept but not this specific claim; add a cross-ref.
- `no_change` — the page mentions terms but the claim is not relevant.

The output is a `plan.json` with a write operation per `(claim_id, page_path)` tuple that needs one. `no_change` entries are listed separately so the verifier can audit coverage (per M2 in `14_evaluation_scaffold.md`).

### Phase 3 — Stage the writes

For every write operation in the plan:

1. Copy the target page from `wiki/<topic>/<page>.md` to `runs/<run_id>/staged/<topic>/<page>.md`.
2. Apply the edit to the **staged** copy using the surgical `str_replace` primitive from `04_guardian_agent.md`. The exactly-one-match rule still holds — mismatches fail the cascade at this point, not after commit.
3. Record the diff and the expected post-state hash in `runs/<run_id>/diffs/<topic>/<page>.diff`.

Four new structural operations in the staged write layer (they do not exist as direct MCP tools — the guardian uses them internally through higher-level workflows):

- `stage_merge(page, claim, quote_anchor)` — elaboration path; adds to an existing section.
- `stage_hedge(page, existing_claim, new_claim, new_quote_anchor, old_source, new_source)` — contradiction path; wraps the section in `::: disputed` with dated markers.
- `stage_new_page(topic, slug, content)` — when a claim introduces a concept no existing page covers.
- `stage_cross_ref(from_page, to_page, label)` — when two pages should link to each other.

All four are thin helpers over the staged `str_replace` + file creation primitives. KISS.

### Phase 4 — Plan `wiki/index.md` and `wiki/overview.md` updates

Every cascade touches index and overview. The plan stages updates to both:

- `index.md` — add new pages, update any touched pages' summaries.
- `overview.md` — update the *Recent updates* list (always) and the *Contested claims* list (only if hedges were applied in this run).

These updates ARE subject to the verifier pass. The verifier's convergence check (`13_hostile_verifier.md` per-run check #2) specifically audits whether every hedge-staged write has a corresponding overview entry.

### Phase 4.5 — Write the belief sidecar

For every staged page, the guardian also writes a `<page>.beliefs.json` sidecar in `runs/<run_id>/staged/<topic>/<page>.beliefs.json` per `19_belief_revision.md`. The sidecar lists:

- The **new beliefs** introduced by the new source (statement + topic + footnote_ids + provenance_ids + optional structured fields).
- The **superseded beliefs** with their original `belief_id`, plus `superseded_at = <run_started_at>`, `superseded_by_belief_id = <new_belief_id>`, `supersession_reason = 'contradicted_by_new_source'`.

This is part of the cascade plan, not a separate operation. The verifier's per-page checks (`13_hostile_verifier.md`) include the belief-coverage and supersession-sanity checks defined in `19_belief_revision.md`. A cascade that hedges a `::: disputed` block in the markdown but fails to update the belief sidecar is a verifier reject.

### Phase 5 — Write plan.json and hand off to verifier

The plan.json records:

```json
{
  "run_id": "2026-04-16-abc123",
  "workspace": "research",
  "triggered_by": "mcp:ingest",
  "source": "raw/papers/acme-rfc-0034.md",
  "claims_extracted": 12,
  "operations": [
    {"op": "stage_merge", "page": "wiki/topics/oauth.md", "claim_id": "c-0003"},
    {"op": "stage_hedge", "page": "wiki/topics/oauth.md", "claim_id": "c-0007", "existing_source": "raw/papers/acme-api-v1.md", "new_source": "raw/papers/acme-rfc-0034.md"},
    {"op": "stage_new_page", "topic": "api-versioning", "slug": "acme-api-versioning"},
    {"op": "stage_cross_ref", "from": "wiki/topics/oauth.md", "to": "wiki/api-versioning/acme-api-versioning.md"},
    {"op": "stage_update_index", "sections": ["topics/oauth.md", "api-versioning/acme-api-versioning.md"]},
    {"op": "stage_update_overview", "sections": ["Recent updates", "Contested claims"]}
  ],
  "touched_pages": [
    "wiki/topics/oauth.md",
    "wiki/api-versioning/acme-api-versioning.md",
    "wiki/index.md",
    "wiki/overview.md"
  ],
  "should_touch_pages_per_grep_audit": [
    "wiki/topics/oauth.md",
    "wiki/api-versioning/acme-api-versioning.md",
    "wiki/topics/auth-errors.md"
  ]
}
```

The difference between `touched_pages` and `should_touch_pages_per_grep_audit` is the M2 coverage signal. The verifier sees it and decides whether to reject or flag as `degraded`.

Once `plan.json` is written and every staged file is in place, the guardian transitions the run to `verifying` and waits for the verifier's verdict.

### Phase 6 — Verify and commit (or reject)

Defined in `13_hostile_verifier.md`. The verifier runs its per-claim, per-page, and per-run checks. On commit, staged → wiki/ via `git mv` + git commit. On reject, staged → `failed/`. Either way, a row lands in `runs` with the final status.

## When `str_replace` finds multiple matches (the sub-problem ai-engineer §3.2 named)

ai-engineer §3.2 observed that a cascade touching 12 pages requires 12 successful one-match replacements, and if any fails the cascade is half-applied. The staged-transaction model already solves this — a failed replacement aborts the run before the verifier is even invoked, nothing commits — but the **failure mode for the individual replacement** still matters. Two sub-rules:

1. **Multi-match on a staged file fails the run.** If `str_replace` on a staged file finds 2+ matches, the whole run is rejected with reason `ambiguous_replacement`. The user's next ingest can retry with more surrounding context in the replacement pattern. The wiki is never half-updated.
2. **Zero-match on a staged file after planning implies the plan was stale.** The plan was built against the live wiki; if the target string is gone from the staged copy (usually because another concurrent operation already changed it between plan and stage), the run is rejected with reason `stale_plan` and the user re-runs. Since `08_mcp_integration.md` enforces workspace-level single-writer locking (see `18_secrets_and_hooks.md` section on concurrent writes), this should be rare — but when it happens, it fails loud.

## Interaction with M2

`14_evaluation_scaffold.md` M2 measures cascade coverage directly from the `plan.json` files. Every `touched_pages` set is compared against the `should_touch_pages_per_grep_audit` set from the same run. Cumulative M2 across all recent runs is the weekly signal.

When M2 drops below 0.70 (broken), ingests are blocked. This means: *a pattern of under-cascading cannot continue indefinitely without surfacing*. The guardian cannot silently skip cascade work to save tokens; the eval scaffold catches it within a week.

## SOLID application

- **Single Responsibility.** This doc defines convergence policy and cascade workflow only. Transaction semantics live in `13_hostile_verifier.md`. Eval live in `14_evaluation_scaffold.md`.
- **Open/Closed.** Adding a new cascade operation (e.g., `stage_archive_snapshot`) is a new helper, not a modification of existing operations.
- **Liskov.** Every staged operation is a pure function from `(run_id, target_path, content, metadata) → (staging_effect, plan_entry)`. Replaceable without breaking the run.
- **Interface Segregation.** `stage_merge`, `stage_hedge`, `stage_new_page`, `stage_cross_ref` are small, named, single-purpose. The guardian chooses the right one per claim; it does not have to figure out the general case.
- **Dependency Inversion.** The staging layer depends on an injected `RunContext` — a handle to the staging directory and the run's plan.json builder. The `str_replace` primitive is a pure text function injected from the tool surface in `04_guardian_agent.md`. Unit tests can stage writes against an in-memory directory.

## DRY notes

- **One hedge marker shape.** `::: disputed` with "Updated YYYY-MM-DD per" is used everywhere. The verifier grep'es for it; overview.md links to it; M5 self-consistency understands it.
- **One cascade workflow.** Elaboration, contradiction, supersession, and new-page are all modeled as stage operations. No separate code path per case.
- **One transaction mechanism.** Cascade and individual-write and synthesis-run all use the `13_hostile_verifier.md` staging. No "cascade transaction" concept beyond the run itself.

## KISS notes

- One rule: hedge with dated markers.
- One markdown convention: `::: disputed` + "Updated YYYY-MM-DD per".
- Four stage operations: merge, hedge, new_page, cross_ref.
- One failure mode for ambiguous replacements: reject the whole run.
- One signal for under-coverage: M2.

## What this doc does NOT cover

- **The run state machine and commit semantics** — `13_hostile_verifier.md`.
- **The MCP tool surface the guardian uses for writes** — `04_guardian_agent.md` (still the canonical `write`, `delete`, `str_replace`, etc.).
- **How M2 is computed** — `14_evaluation_scaffold.md`.
- **What the verifier actually checks** — `13_hostile_verifier.md` (though this doc names the specific checks the verifier runs to enforce the hedge policy).
- **Interactive query answering** — unchanged from `04_guardian_agent.md`.

## Summary

When sources contradict, hedge with dated markers. When the guardian cascades, it stages every write in a transaction. The transaction fails atomically — no partial cascade can ever reach the live wiki. The verifier enforces both the hedge convention and the coverage audit. M2 catches under-cascade patterns within a week. Four stage operations (merge, hedge, new_page, cross_ref) cover every case without new concepts.

The wiki's shape is now a function of the underlying knowledge, not ingest order. Karpathy's graveyard failure mode is closed.
