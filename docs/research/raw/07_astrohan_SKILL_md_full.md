# Source: Astro-Han/karpathy-llm-wiki — SKILL.md (full)
URL: https://raw.githubusercontent.com/Astro-Han/karpathy-llm-wiki/main/SKILL.md
Fetched: 2026-04-15
Status: Fetched full content via WebFetch.

This is the single most detailed specification of the ingest/query/lint workflows encountered so far. Preserved as-is.

---

```yaml
---
name: karpathy-llm-wiki
description: "Use when building or maintaining a personal LLM-powered knowledge base. Triggers: ingesting sources into a wiki, querying wiki knowledge, linting wiki quality, 'add to wiki', 'what do I know about', or any mention of 'LLM wiki' or 'Karpathy wiki'."
---
```

## Overview

This system enables building a persistent, compounding knowledge base through three core operations: **Ingest** (fetch sources and compile them into articles), **Query** (search and synthesize answers), and **Lint** (maintain quality).

The foundational principle: "The LLM writes and maintains the wiki; the human reads and asks questions."

## Directory Structure

- **raw/** — Immutable source material, organized by topic subdirectories
- **wiki/** — Compiled knowledge articles with two mandatory files:
  - `wiki/index.md` — Global index with article links, summaries, and update dates
  - `wiki/log.md` — Append-only operation log
- **SKILL.md** — Schema and workflow definition
- **references/** — Templates for raw files, articles, archives, and index entries

## Ingest Workflow

### Fetch Phase
1. Retrieve source content using available tools; request direct paste if needed
2. Select or create a topic subdirectory in `raw/`
3. Save as `raw/<topic>/YYYY-MM-DD-descriptive-slug.md` (omit date if unknown)
4. Append numeric suffix if filename exists
5. Include metadata header with source URL, collected date, published date
6. Preserve original text while cleaning formatting noise

### Compile Phase
Place content based on relationship to existing articles:
- **Overlapping thesis** → Merge into existing article; add new source to Sources/Raw
- **Novel concept** → Create new article named after the concept
- **Multi-topic scope** → Place in most relevant directory with cross-references

When sources contradict, annotate disagreements with source attribution.

### Cascade Updates
After compiling the primary article:
1. Review same-topic articles for affected content
2. Scan `wiki/index.md` entries across other topics
3. Update every materially affected article with refreshed Updated dates
4. Archive pages remain point-in-time snapshots (never cascade-updated)

### Post-Ingest Tasks
- Update `wiki/index.md`: add/modify entries for touched articles
- Append to `wiki/log.md` with timestamp, operation type, and cascade-updated article list

## Query Workflow
1. Read `wiki/index.md` to identify relevant articles
2. Synthesize answer from those articles
3. Cite sources using markdown links with project-root-relative paths
4. Output answer in conversation (no file writes unless archiving requested)

### Archiving Query Results
When user requests saving the answer:
1. Write new wiki page using archive template (not merged into existing articles)
2. Convert citations from project-root paths to file-relative paths
3. Include Sources field with links to cited articles; omit Raw field
4. Update `wiki/index.md` with `[Archived]` prefix on summary
5. Append to `wiki/log.md` with archive notation

## Lint Workflow

### Deterministic Checks (Auto-Fixed)
- **Index consistency** — add missing entries with fallback dates; mark broken links `[MISSING]`
- **Internal links** — fix paths when exactly one target found; report ambiguous cases
- **Raw references** — validate all links to raw/ files; fix unambiguous mismatches
- **See Also** — add/remove cross-references between related articles

### Heuristic Checks (Report Only)
- Factual contradictions
- Outdated claims superseded by newer sources
- Missing conflict annotations
- Orphan pages without inbound links
- Missing cross-topic references
- Frequently-mentioned but undocumented concepts
- Archive pages citing substantially-updated source articles

### Post-Lint Logging
Append summary to `wiki/log.md` with date, issue count, and auto-fixes applied.

## Key Conventions
- All wiki/ links use file-relative paths; conversation citations use project-root-relative paths
- One topic subdirectory level only (no deeper nesting)
- Dates: today's date for logs/collection; Updated reflects knowledge change; Published from source
- Ingest and Archive both update index.md and log.md; plain queries do not write files
- Preserve original source language; annotate disagreements with attribution
- Metadata includes: Sources (author/org/publication + date, semicolon-separated), Raw (markdown links to raw/ files)
