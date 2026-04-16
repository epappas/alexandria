# 19 — Belief Revision and Traceability

> **Cites:** `13_hostile_verifier.md` (verbatim quote anchors), `15_cascade_and_convergence.md` (hedge convergence policy), `06_data_model.md` (`wiki_claim_provenance`), `research/reference/14_mempalace.md` (the temporal-validity idea we previously deferred — now adopted at the belief layer, not the retrieval layer).

## The problem this doc closes

The user's gathered knowledge is not static. As the project progresses, new sources update or supersede prior beliefs. The user wants to ask:

- *"What do I believe right now about X?"*
- *"Why do I believe it — what's the supporting source?"*
- *"What did I think six months ago about the same thing?"*
- *"What changed my mind?"*
- *"Show me every belief that changed in the last month."*

The cascade workflow already updates the wiki page (`15_cascade_and_convergence.md`). The provenance chain already links footnotes to raw sources (`13_hostile_verifier.md`). The convergence policy already hedges contradicting claims with dated markers. **What is missing** is treating the belief itself — the structured assertion — as a first-class queryable unit with stable identity, supersession history, and a verified provenance trail back to the verbatim source quote.

This doc adds that layer **without changing the source of truth**. The wiki page remains canonical. Beliefs are a materialized index over wiki pages, extracted at write time, verified by the same hostile verifier, queryable via SQLite + a new `why` MCP tool. Deleting `wiki_beliefs` and running `llmwiki reindex --rebuild-beliefs` reconstructs the table from the wiki pages on disk. Files-first invariant preserved.

## What is a belief

A belief is **one assertion the wiki currently makes**, attached to:

1. The wiki page (and section) where it lives in human-readable prose.
2. The footnote(s) that cite supporting raw sources.
3. The verbatim quote anchor(s) in those raw sources, verified by hash.
4. The run that asserted it.
5. The temporal envelope: when the wiki started believing it, when (if ever) it was superseded, what superseded it, why.

Beliefs are not a separate ontology. They are not RDF triples enforced by a schema. They are the **structured shadow** of the assertions already in the wiki, extracted by the writer, checked by the verifier, queryable by the user.

### Required and optional fields

```sql
CREATE TABLE wiki_beliefs (
  belief_id          TEXT PRIMARY KEY,
  workspace          TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,

  -- The belief itself (REQUIRED)
  statement          TEXT NOT NULL,           -- natural-language claim, ≤ 280 chars, verbatim or paraphrased from the wiki page
  topic              TEXT NOT NULL,           -- top-level subject area (matches a topic directory or a stable label)

  -- Optional structured form (best-effort, may be NULL)
  subject            TEXT,                    -- noun phrase: "OAuth refresh endpoint", "Acme Corp", "auth-flow"
  predicate          TEXT,                    -- relation: "is_at", "depends_on", "was_decided_by", "has_value"
  object             TEXT,                    -- noun phrase: "/auth/v2/refresh", "Maya", "JWT"

  -- Where it lives (REQUIRED)
  wiki_document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  wiki_section_anchor TEXT,                   -- markdown heading anchor for the section the belief lives under
  footnote_ids       TEXT NOT NULL,           -- JSON array of footnote IDs in the wiki page, e.g. ["1","2"]
  provenance_ids     TEXT NOT NULL,           -- JSON array of wiki_claim_provenance.id values

  -- Temporal envelope of the wiki's belief (REQUIRED for current, NULL for historical)
  asserted_at        TEXT NOT NULL,           -- when the wiki started believing this
  asserted_in_run    TEXT NOT NULL REFERENCES runs(run_id),
  superseded_at      TEXT,                    -- when the wiki stopped believing this (NULL = current)
  superseded_by_belief_id  TEXT REFERENCES wiki_beliefs(belief_id),
  superseded_in_run  TEXT REFERENCES runs(run_id),
  supersession_reason TEXT,                   -- 'contradicted_by_new_source'|'elaborated'|'manual_correction'|'source_drifted'

  -- Source-level temporal validity (when the SOURCE itself says the fact applies)
  source_valid_from  TEXT,                    -- e.g. "RFC 0034 says this took effect 2026-03-15"
  source_valid_to    TEXT,                    -- e.g. "RFC 0034 says deprecation 2027-01"

  -- Derived signals
  supporting_count   INTEGER NOT NULL DEFAULT 1,    -- number of provenance entries supporting this belief
  contradicting_belief_ids TEXT,              -- JSON array of belief_ids that disagree (lint-populated)
  confidence_hint    TEXT,                    -- 'single_source'|'multi_source'|'authoritative'|'contested'

  created_at         TEXT NOT NULL,

  CHECK (supersession_reason IS NULL OR superseded_at IS NOT NULL),
  CHECK (length(statement) <= 280)
);

CREATE INDEX idx_beliefs_workspace_topic    ON wiki_beliefs(workspace, topic);
CREATE INDEX idx_beliefs_workspace_current  ON wiki_beliefs(workspace) WHERE superseded_at IS NULL;
CREATE INDEX idx_beliefs_subject_predicate  ON wiki_beliefs(workspace, subject, predicate) WHERE subject IS NOT NULL;
CREATE INDEX idx_beliefs_wiki_doc           ON wiki_beliefs(wiki_document_id);
CREATE INDEX idx_beliefs_asserted_at        ON wiki_beliefs(workspace, asserted_at DESC);
CREATE INDEX idx_beliefs_superseded_at      ON wiki_beliefs(workspace, superseded_at DESC) WHERE superseded_at IS NOT NULL;

-- FTS over statement for free-text "why do I believe X" queries
CREATE VIRTUAL TABLE wiki_beliefs_fts USING fts5(
  statement, topic, subject, predicate, object,
  content='wiki_beliefs', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```

The `statement` is the canonical natural-language form. The structured `subject`/`predicate`/`object` are encouraged but optional — users who want graph-shaped queries get them; users who want free-text queries use the FTS index. Both work. **No schema enforcement on the structured fields** — the writer fills them in best-effort, the verifier doesn't reject for missing structured fields.

The 280-character limit on `statement` is deliberate: a belief is one tweet-sized claim. Longer assertions decompose into multiple beliefs. This keeps each row narrow enough to render in `why` output without overwhelming the user.

## On-disk representation: belief sidecars

The wiki page remains canonical. Beliefs live in a **sidecar JSON file** next to the markdown:

```
wiki/topics/auth.md              ← human-readable wiki page
wiki/topics/auth.beliefs.json    ← machine-readable belief extract
```

The sidecar mirrors the rows in `wiki_beliefs` for that page:

```json
{
  "page": "wiki/topics/auth.md",
  "page_anchor_root": "#",
  "beliefs": [
    {
      "belief_id": "b-2026-04-15-acme-auth-001",
      "statement": "Acme's OAuth refresh endpoint is /auth/v2/refresh as of 2026-03-15.",
      "topic": "auth",
      "subject": "Acme OAuth refresh endpoint",
      "predicate": "is_at",
      "object": "/auth/v2/refresh",
      "wiki_section_anchor": "#token-refresh-in-oauth-flow",
      "footnote_ids": ["2"],
      "provenance_ids": ["prov-acme-rfc-0034-3"],
      "source_valid_from": "2026-03-15",
      "source_valid_to": null
    },
    {
      "belief_id": "b-2026-01-10-acme-auth-001",
      "statement": "Acme's OAuth refresh endpoint is /oauth/refresh.",
      "topic": "auth",
      "subject": "Acme OAuth refresh endpoint",
      "predicate": "is_at",
      "object": "/oauth/refresh",
      "wiki_section_anchor": "#token-refresh-in-oauth-flow",
      "footnote_ids": ["1"],
      "provenance_ids": ["prov-acme-api-v1-12"],
      "superseded_at": "2026-04-15",
      "superseded_by_belief_id": "b-2026-04-15-acme-auth-001",
      "supersession_reason": "contradicted_by_new_source"
    }
  ]
}
```

Both the current belief and its superseded ancestor live in the sidecar. The sidecar is git-versioned alongside the page. `llmwiki reindex --rebuild-beliefs` walks `wiki/**/*.beliefs.json` and rebuilds `wiki_beliefs` deterministically.

**Why a sidecar instead of frontmatter:** belief metadata can grow large (10-30 beliefs per page), and embedding it in the markdown frontmatter would bloat the page and make diffs noisy. The sidecar is structured, machine-targeted, and never meant for human reading. The page itself stays clean.

## Extraction protocol — writer emits, verifier checks

This is where the new mechanism plugs into the existing workflow without changing it.

### At write time

When the guardian writes (or updates) a wiki page during a staged run:

1. **Write the page itself** as before — markdown with footnotes and `::: disputed` markers per `15_cascade_and_convergence.md`.
2. **Emit the belief sidecar** to `runs/<run_id>/staged/<topic>/<page>.beliefs.json`. For each substantive claim in the page body, the guardian creates a belief object with at minimum: `statement`, `topic`, `wiki_section_anchor`, `footnote_ids`, `provenance_ids`. Optional structured fields when the guardian can extract them confidently.
3. **Apply supersession** for any existing belief on the same `(subject, predicate)` (or, if structured fields are absent, on the same `topic` + close `statement` match): set `superseded_at`, `superseded_by_belief_id`, `superseded_in_run`, `supersession_reason`.

The guardian does not invent beliefs. Every belief must correspond to an actual claim in the wiki page text and an actual footnote citation. The verifier enforces this.

### At verify time

The hostile verifier (`13_hostile_verifier.md`) gains four additional per-page checks:

1. **Coverage.** Every footnote citation in the staged page body must correspond to at least one belief in the sidecar. Conversely, every belief's `footnote_ids` must reference footnotes that exist in the page. Mismatches reject the run.
2. **Provenance link.** Every belief's `provenance_ids` must correspond to entries in the staged `wiki_claim_provenance` extension for this run. The provenance entries themselves carry the verbatim quote anchors that the deterministic check (`13_hostile_verifier.md` check #3) validates against the live raw source.
3. **Supersession sanity.** When the new run supersedes an existing belief, the new belief's claim must actually contradict (or refine) the old one. The verifier reads both statements and votes — if it cannot tell why one supersedes the other, the run is rejected with reason `unjustified_supersession`.
4. **Statement support.** The verifier reads each belief's `statement` and the cited verbatim quote and votes on whether the quote supports the statement. Failures land in the per-belief findings — the verdict policy from `13_hostile_verifier.md` applies (commit / reject / revise).

These checks reuse the verifier's existing per-claim mechanism. No new agent, no new infrastructure. DRY: the same verifier that protects citations also protects beliefs.

### At commit time

When the verifier votes `commit`:

1. The page moves from `staged/` into `wiki/`.
2. The sidecar moves alongside it.
3. SQLite inserts new beliefs from the sidecar into `wiki_beliefs`.
4. SQLite UPDATEs the existing rows for any superseded beliefs (`superseded_at`, `superseded_by_belief_id`, `superseded_in_run`, `supersession_reason`).
5. `wiki_beliefs_fts` is updated by trigger.

If the run has no belief sidecar (e.g., a structural-page edit on `wiki/log.md`), nothing happens to `wiki_beliefs`. Belief extraction is required only for content pages, which are exactly the pages the verifier requires citations on. The exempt structural pages are exempt from both.

## The supersession workflow — what changes when source N contradicts source M

Restating with belief plumbing:

1. **Cascade phase (`15_cascade_and_convergence.md`).** The guardian reads the new source, finds the contradicting claim, and stages a `stage_hedge` operation on the affected wiki page. The page now has a `::: disputed` block with both the old citation (to source M) and the new citation (to source N), each with a verbatim quote anchor.
2. **Belief sidecar update.** The guardian updates the page's `.beliefs.json`:
   - The old belief is **kept** with its original `belief_id`, plus `superseded_at = now()`, `superseded_by_belief_id = <new>`, `superseded_in_run = <current>`, `supersession_reason = 'contradicted_by_new_source'`.
   - The new belief is **added** with a new `belief_id`, citing source N's footnote and provenance entry.
3. **Verifier passes.** Convergence check enforces the hedge marker is present; coverage check enforces both beliefs are in the sidecar; provenance link enforces both citations have valid quote anchors; supersession sanity check enforces that the new belief actually contradicts the old one (otherwise it is an `elaborated` case, not a `contradicted_by_new_source`).
4. **Commit.** Both beliefs land in `wiki_beliefs`. The current belief is queryable as the not-superseded row; the historical belief is queryable as the superseded row. Both rows reference the same `topic` and `subject`/`predicate` — that's how `why` finds them together.

The user's *"what did I think in April?"* query is now a single SQL filter:

```sql
SELECT statement, asserted_at, superseded_at
  FROM wiki_beliefs
 WHERE workspace = ?
   AND subject = 'Acme OAuth refresh endpoint'
   AND asserted_at < '2026-05-01'
   AND (superseded_at IS NULL OR superseded_at >= '2026-05-01')
 ORDER BY asserted_at DESC;
```

Returns the belief that was current on April 30, 2026, with full provenance trail.

## The `why` MCP tool

A new tool, joining the surface defined in `04_guardian_agent.md`. Read-only. Returns structured belief lookups.

```python
why(
  workspace: str,
  query: str,                    # natural-language topic, subject, or belief_id
  since: str | None = None,      # ISO date — only beliefs current at or after this date
  until: str | None = None,      # ISO date — only beliefs current at or before this date
  include_history: bool = True,  # include superseded beliefs
) -> WhyAnswer
```

### Resolution

The `query` parameter is resolved in this order:

1. **Exact `belief_id`** — direct lookup.
2. **Exact `subject` + optional `predicate`** — when the user passes `"Acme OAuth refresh endpoint"`, match `subject` first.
3. **Topic match** — when the user passes a topic name like `"auth"`.
4. **FTS over `statement`** — full-text fallback with ranking.

The first non-empty match wins. If multiple resolvers tie (e.g., a topic name happens to also match a subject), the tool returns ALL matches with a `match_type` field per result so the agent or user can disambiguate.

### Response shape

```json
{
  "query": "Acme OAuth refresh endpoint",
  "match_type": "subject",
  "current_beliefs": [
    {
      "belief_id": "b-2026-04-15-acme-auth-001",
      "statement": "Acme's OAuth refresh endpoint is /auth/v2/refresh as of 2026-03-15.",
      "topic": "auth",
      "asserted_at": "2026-04-15",
      "asserted_in_run": "run-2026-04-15-abc",
      "wiki_page": "wiki/topics/auth.md#token-refresh-in-oauth-flow",
      "supporting_sources": [
        {
          "raw_path": "raw/papers/acme-rfc-0034.md",
          "page_hint": 3,
          "quote": "v2 moves the refresh endpoint to /auth/v2/refresh. The legacy path returns 301 until 2026-12.",
          "quote_hash": "a1b2c3d4...",
          "verified_against_source": true,
          "verified_at": "2026-04-16T14:23:00Z"
        }
      ]
    }
  ],
  "history": [
    {
      "belief_id": "b-2026-01-10-acme-auth-001",
      "statement": "Acme's OAuth refresh endpoint is /oauth/refresh.",
      "asserted_at": "2026-01-10",
      "asserted_in_run": "run-2026-01-10-pqr",
      "superseded_at": "2026-04-15",
      "superseded_by_belief_id": "b-2026-04-15-acme-auth-001",
      "superseded_in_run": "run-2026-04-15-abc",
      "supersession_reason": "contradicted_by_new_source",
      "wiki_page": "wiki/topics/auth.md#token-refresh-in-oauth-flow",
      "supporting_sources": [
        {
          "raw_path": "raw/papers/acme-api-spec-v1.md",
          "page_hint": 12,
          "quote": "Token refresh is served at the path /oauth/refresh.",
          "quote_hash": "e5f6g7h8...",
          "verified_against_source": true,
          "verified_at": "2026-04-16T14:23:00Z"
        }
      ]
    }
  ],
  "contradicting_beliefs": [],
  "supersession_chain": ["b-2026-01-10-acme-auth-001", "b-2026-04-15-acme-auth-001"]
}
```

The `verified_against_source` field is computed at query time by re-running the deterministic hash check from `13_hostile_verifier.md`. If the raw source has been re-synced and the hash no longer matches, the field is `false` and the user knows the citation has drifted — even if the belief itself is still current.

This is the explainability surface the user asked for. **Every belief traces to a verbatim source quote that is checkable in real time, plus the run that asserted it, plus the run that superseded it (if any).** No model judgment in the trace itself; the LLM only ever asserted the belief — the trace is deterministic SQL + hash math.

## CLI

```
llmwiki why "Acme OAuth refresh endpoint"
llmwiki why --workspace customer-acme --since 2026-01-01 "auth"
llmwiki beliefs list --topic auth [--current-only]
llmwiki beliefs history <belief_id>
llmwiki beliefs supersede <old_id> <new_id> --reason "manual_correction"
llmwiki beliefs export [--workspace X] [--format json|csv]
llmwiki beliefs verify [--workspace X]      # re-runs hash check on every supporting quote
```

`llmwiki beliefs verify` is the manual equivalent of M1 (citation fidelity from `14_evaluation_scaffold.md`) at the belief level — it re-validates every belief's quote anchor against the live raw source and flags drifts.

## Reindex semantics

`llmwiki reindex --rebuild-beliefs` walks every workspace, reads every `*.beliefs.json` sidecar, and rebuilds `wiki_beliefs` + `wiki_beliefs_fts`. The sidecar is the source of truth for beliefs; the SQLite table is the queryable index. Filesystem-first invariant honoured.

If a sidecar is missing or unparseable, the reindex emits a warning and skips that page's beliefs. The page itself is unaffected; the user's next ingest of that page will regenerate the sidecar from scratch.

## How beliefs make M1 sharper

The evaluation scaffold's M1 (citation fidelity from `14_evaluation_scaffold.md`) currently samples 50 random claims from the wiki and measures whether their footnotes are supported. With beliefs, M1 has a **structured population to sample from** — every belief is a claim with a known location, footnote, and quote anchor. The sample becomes more deterministic and easier to compare across weeks.

Updated M1 procedure:

1. Sample 50 random current beliefs (`superseded_at IS NULL`) from `wiki_beliefs`.
2. For each: re-run the deterministic hash check on the supporting quote against the live raw source.
3. For each that passes hash check: spawn a verifier run with the prompt *"Read this source quote and the belief statement. Vote: supports / partially_supports / does_not_support."*
4. Metric: `M1 = supports / total`.

The hash check is the cheap gate; the LLM vote is the expensive but rarer step. **A belief that fails the hash check is automatically `does_not_support`** — no LLM call needed. This makes M1 cheaper and more reliable.

## Invariant additions

Adding to `01_vision_and_principles.md`:

**20. Beliefs are explainable and traceable.** Every assertion in the wiki is recorded as a structured belief with stable identity, supersession history, and a provenance chain to a verbatim source quote whose hash is checked deterministically against the live raw file. The user can ask *"why do I believe X?"* and get the full chain — current belief, supporting sources with verbatim quotes, prior superseded beliefs, the run that changed the wiki's mind, and the reason for the change — in one tool call. Defined in `19_belief_revision.md`.

## SOLID application

- **Single Responsibility.** This doc adds the belief layer. The convergence policy stays in `15`; the staging mechanism stays in `13`; the citation hash check stays in `13`'s deterministic check. Beliefs are the **structured shadow** of all three, not a replacement for any.
- **Open/Closed.** Adding a new `supersession_reason` value or a new structured field (`object_type`, `confidence_evidence`) is additive. Existing reads continue to work.
- **Liskov.** Every belief row conforms to the same shape — current and historical, structured and free-text, single-source and multi-source. Code that processes beliefs does not branch on these axes.
- **Interface Segregation.** The `why` tool returns only what the user asked for. The `beliefs list` CLI is a separate narrower surface. The eval scaffold uses yet another (sample-by-id) interface.
- **Dependency Inversion.** The belief extractor is an injected component (`BeliefExtractor`) called by the writer. The verifier's belief checks consume an injected `BeliefValidator`. Tests substitute fakes.

## DRY application

- **One provenance chain.** `wiki_claim_provenance` (from `06_data_model.md`) is the ground truth. Beliefs reference it via `provenance_ids`. The verbatim quote anchor lives in one place; beliefs are pointers.
- **One verifier.** The hostile verifier from `13_hostile_verifier.md` checks beliefs alongside citations. No separate "belief verifier" agent.
- **One supersession mechanism.** The cascade workflow's hedge marker (in the wiki page) and the belief's `superseded_by_belief_id` (in the sidecar) are two views of the same operation. The cascade workflow is the writer; both views are derived from the same plan.
- **One reindex command.** `llmwiki reindex` rebuilds the document layer; `--rebuild-beliefs` extends it to walk sidecars. Same machinery, additional pass.
- **One temporal model.** `asserted_at` / `superseded_at` mirror the existing `documents.created_at` / `documents.superseded_by` model from `06_data_model.md`. Same vocabulary.

## KISS application

- **No new agent.** The same hostile verifier checks beliefs.
- **No structured query language.** Free-text via FTS5 plus indexed `subject`/`predicate`/`object` covers every query the user actually wants. No SPARQL, no Datalog, no Cypher.
- **No graph store.** Beliefs are rows. Supersession is a foreign key. Contradictions are an array column. The "graph" is whatever the agent assembles at query time via repeated `why` calls.
- **No new file format.** Sidecars are JSON next to markdown. Git versions both. The user can `cat` either.
- **Optional structured fields.** Users who want graph queries get them. Users who don't can rely on `statement` + FTS. Both work.

## What this doc does NOT cover

- **The wiki page markdown shape and citation format** — `06_data_model.md`, `04_guardian_agent.md`.
- **The verbatim quote anchor mechanism** — `13_hostile_verifier.md`.
- **The cascade workflow that triggers belief supersession** — `15_cascade_and_convergence.md`.
- **The hostile verifier's existing per-claim checks** — `13_hostile_verifier.md`.
- **Evaluation metrics** — `14_evaluation_scaffold.md`. M1 gets sharper with beliefs but the metric definition lives there.
- **Storage and migration of `wiki_beliefs` table** — `06_data_model.md` (additions threaded in via the schema migration framework from `16_operations_and_reliability.md`).

## Summary

Beliefs are first-class structured rows extracted from wiki pages at write time, stored in `wiki_beliefs` and as `*.beliefs.json` sidecars next to the markdown. Each belief has stable identity, supersession history, and a provenance chain to a verbatim source quote whose hash is checked deterministically. The hostile verifier checks beliefs as part of every write. The `why` MCP tool answers *"what do I believe and why"* with a full trace. The `beliefs verify` CLI re-validates every quote anchor on demand.

The wiki page remains the source of truth. Beliefs are a queryable view over it. The retroactive query the user asked for — *"what did I think in April?"* — is now a single indexed SQL filter that returns a complete, verifiable, explainable answer.

This closes the loop on belief revision, traceability, and explainability without compromising any existing invariant.
