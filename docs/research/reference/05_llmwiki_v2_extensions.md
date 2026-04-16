# Reference: LLM Wiki v2 (rohitg00) — Production Extensions

**Source:** `raw/03_rohitg00_gist_v2.md`

A forward-looking extension gist. Most of it is not MVP material, but three ideas are worth explicit consideration before we freeze the data model.

## Ideas worth tracking

1. **Memory lifecycle / confidence scoring.** Claims carry a confidence score, supersession of outdated claims, and Ebbinghaus-style forgetting curves. Tiered memory: working / episodic / semantic / procedural.
   - *Implication:* the `documents` row is not the right unit for confidence. We'd need a claim/statement table. Defer, but design the schema so we can add `confidence REAL` and `superseded_by UUID` later without migrating.

2. **Typed relationships.** Move beyond flat markdown — entities with edges like `uses`, `depends_on`, `contradicts`.
   - *Implication:* wiki pages are our unit of truth, but we can extract `(subject, predicate, object, citation)` tuples into a side table for lint and graph queries. MVP can live without this.

3. **Hybrid search.** v2 proposes BM25 + vector + graph traversal once you cross ~100 pages.
   - *Decision:* **rejected for alexandria.** The v2 framing assumes a static retrieval pipeline; we have committed to agentic navigation instead (see `12_agentic_retrieval.md`). Scale problems past a few hundred pages are solved by sharper orientation documents and subagent patterns, not by adding a vector index. We keep FTS5 as the broad-keyword primitive and add `grep` for exact-match. No vectors.

## Ideas we explicitly reject (for MVP)
- **Multi-agent mesh sync.** Overkill for a single-user wiki.
- **Crystallization of session transcripts into wiki pages.** Nice feature; not core.
- **Self-healing contradiction resolution.** Lint reports; a human decides. Automating this is a trust disaster waiting to happen.

## Critical commentary we should take seriously
@gnusupport's critique — no implementation specifics for confidence mechanics, latency, accuracy, versioning, provenance — maps to our non-functional requirements list. When we ship, we need concrete numbers for:
- Ingest latency (per source type).
- Query p50/p95.
- Wiki-write version history (do we keep old revisions or rely on the `version` counter?).
- Provenance: every wiki claim traceable to a raw-source span.
