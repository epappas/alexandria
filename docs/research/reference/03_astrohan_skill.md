# Reference: Astro-Han karpathy-llm-wiki — SKILL.md Workflow Specification

**Sources:** `raw/05_astrohan_karpathy_llm_wiki_repo.md`, `raw/07_astrohan_SKILL_md_full.md`, `raw/13_astrohan_references_and_examples.md`
**Local clone:** `/tmp/karpathy-llm-wiki`

This is packaged as an Agent Skill (the `agentskills.io` standard). The value for us is not the packaging — it's the precise workflow spec and the four file templates. Every ambiguity in Karpathy's gist gets pinned down here.

## Directory layout (canonical)
```
<project>/
├── raw/<topic>/YYYY-MM-DD-slug.md        # one subdir level only, never deeper
└── wiki/
    ├── <topic>/<concept>.md
    ├── index.md                          # mandatory
    └── log.md                            # mandatory, append-only
```

Initialization happens only on first Ingest: create missing directories and seed `index.md`/`log.md` with empty headings. Query/Lint without an initialized wiki must tell the user to ingest first — never silently create.

## Ingest workflow (pinned down)

### Fetch phase — `raw/`
1. Get source content by any available means; fall back to asking the user to paste.
2. Reuse an existing `raw/<topic>/` if the topic is close enough; create new only for genuinely distinct topics.
3. Save as `raw/<topic>/YYYY-MM-DD-slug.md`. Slug kebab-case, ≤ 60 chars. If published date unknown, omit the date prefix but still set `Published: Unknown` in metadata.
4. Collision → numeric suffix (`slug-2.md`).
5. Preserve original text; clean formatting noise; don't rewrite opinions.

### Compile phase — `wiki/`
Three placement rules, *not mutually exclusive*:
- **Same core thesis** → merge into the existing article, add source to Sources/Raw.
- **New concept** → create a new article named after the concept (not the raw filename).
- **Spans topics** → place in the most relevant topic + add See Also cross-references.

Contradictions are annotated with source attribution. When merging, note the conflict in the merged article. When conflicting claims live in separate articles, note both and cross-link.

### Cascade updates — the compounding property
After compiling the primary article:
1. Scan same-topic articles for affected content.
2. Scan `wiki/index.md` cross-topic for related concepts.
3. Update every materially affected article; refresh their `Updated` date.
4. **Archive pages are never cascade-updated** — they're point-in-time snapshots.

### Post-ingest housekeeping
Update `wiki/index.md`. Append to `wiki/log.md`:
```
## [YYYY-MM-DD] ingest | <primary article title>
- Updated: <cascade-updated article title>
- Updated: <another cascade-updated article title>
```
Omit `- Updated:` lines when no cascade updates occurred.

## Query workflow
1. Read `wiki/index.md` to locate relevant articles.
2. Read them and synthesize.
3. Prefer wiki content over training knowledge. Cite with markdown links.
4. **No file writes** unless the user explicitly asks to archive.

### Archiving (optional on query)
- Write a new page using `archive-template.md`. Never merge into existing articles.
- Sources: links to the wiki articles cited. No Raw field.
- `wiki/index.md` summary prefixed with `[Archived]`.
- Log as `## [YYYY-MM-DD] query | Archived: <page title>`.

## Lint workflow — two authority tiers

### Deterministic (auto-fix)
- **Index consistency** — files missing from index → add with `(no summary)` + metadata date (or file mtime fallback). Index entries pointing nowhere → mark `[MISSING]`, never delete.
- **Internal links** — broken link in body/Sources → search wiki for same name. Exactly one match → fix. Zero or multiple → report.
- **Raw references** — same rule for Raw-field links against `raw/`.
- **See Also** — add obviously missing cross-refs; remove links to deleted files.

### Heuristic (report only, never auto-fix)
- Factual contradictions across articles.
- Outdated claims superseded by newer sources.
- Missing conflict annotations where sources disagree.
- Orphan pages with no inbound links.
- Missing cross-topic references.
- Frequently mentioned but undocumented concepts.
- Archive pages citing source articles that have been substantially updated since archival.

### Post-lint
```
## [YYYY-MM-DD] lint | <N> issues found, <M> auto-fixed
```

## Path conventions (non-negotiable)
- **Inside wiki/ files**: links relative to the current file.
  - Same topic: `other-article.md`.
  - Cross topic: `../other-topic/other-article.md`.
  - To raw: `../../raw/<topic>/<file>.md` (two levels up to project root).
- **In conversation output**: project-root-relative (`wiki/topic/article.md`).
- **One topic subdir level only.** No deeper nesting.

## Metadata date semantics (easy to get wrong)
- `Collected` — today's date when ingested.
- `Published` — source's own date, or `Unknown`.
- `Updated` — when the article's knowledge content last changed (NOT file mtime).
- `Archived` — today's date when archiving a query answer.

## Which operations write which files
| Op | Writes? |
|---|---|
| Ingest | `raw/`, new/updated `wiki/*`, `wiki/index.md`, `wiki/log.md` |
| Query (plain) | nothing |
| Query + archive | new `wiki/<topic>/*.md`, `wiki/index.md`, `wiki/log.md` |
| Lint (deterministic) | `wiki/*` fixes, `wiki/index.md`, `wiki/log.md` |
| Lint (heuristic) | `wiki/log.md` only (report-only findings) |

## What this gives us
A **complete behavioural spec** for the guardian agent. Our Python agent can treat this document as the functional contract: if we implement these rules faithfully, any user familiar with Karpathy's pattern can transfer knowledge with zero retraining. It's also our acceptance-test checklist — each rule above maps to a testable invariant.
