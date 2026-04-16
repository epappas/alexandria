# Reference: atomicmemory/llm-wiki-compiler — Two-Phase Pipeline

**Source:** `raw/06_atomicmemory_llmwiki_compiler.md`
**Local clone:** `/tmp/llm-wiki-compiler`

A TypeScript CLI that treats wiki generation as a deterministic compile step. Not what we're building, but the *pipeline shape* is worth borrowing.

## Key ideas

### Two-phase compile
1. **Phase 1 — Concept extraction.** Walk all sources, ask the LLM to extract structured concepts. Do this for every source before writing anything.
2. **Phase 2 — Page generation.** Generate wiki pages with `[[wikilink]]` resolution from the extracted concept pool.

Benefits of the separation:
- **Order-independent** — concept merge happens globally, so source processing order doesn't matter.
- **Fail before writing** — LLM failures in Phase 1 don't leave a half-written wiki.
- **Concept merging** — a concept mentioned in multiple sources becomes one page, not duplicates.

### Incremental by SHA-256
Each source's SHA is stored; unchanged sources are skipped on recompile. Only deltas re-enter the LLM. This is the cheapest way to support "watch" mode and keeps recompile costs bounded.

### Query compounding
`llmwiki query "..." --save` writes the answer as a new wiki page and rebuilds the index, so future queries use it as context. This makes "ask-and-save" a first-class operation, not an afterthought.

### Provenance
Every paragraph gets a marker `^[filename.md]` pointing back to the source that contributed the claim. Frontmatter carries the full source list. Character-limit truncation is explicit: `truncated: true` and original length recorded, so downstream consumers can tell they're working with partial content.

### Obsidian-compatible output
```
wiki/
  concepts/     one .md per concept with YAML frontmatter
  queries/      saved query answers (included in index)
  index.md      auto-generated TOC
```

## Honest limitations the repo admits
- Best for small, high-signal corpora (~dozen sources).
- Index-based query routing only; no semantic search yet.
- Anthropic-only.

## Roadmap worth noting
- Semantic search / embeddings for larger corpora.
- Multi-provider support.
- MCP server for agent integration (not there yet).

## What we borrow
1. **Two-phase ingest** — extract concepts globally before writing, so we can merge and de-duplicate.
2. **SHA-based incremental recompile** — we'll need this the moment we wire in sync-from-Notion or sync-from-git.
3. **Paragraph-level provenance markers** — stronger than Lucas's footnote model; pairs well with explicit citations for verifiability.
4. **Explicit truncation signaling** — always tell the caller when content is partial.

## What we don't borrow
- CLI-first design (we're a service).
- Filesystem wiki/ layout (we're DB-backed like lucasastorian).
- TypeScript.
