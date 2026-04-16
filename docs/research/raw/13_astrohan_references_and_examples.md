# Source: Astro-Han/karpathy-llm-wiki — Templates and examples
Local clone: /tmp/karpathy-llm-wiki
Fetched: 2026-04-15

The full SKILL.md is captured in `07_astrohan_SKILL_md_full.md`. This file captures the four canonical templates plus a sample log entry. These templates double as the file schema any implementation must honour.

---

## references/raw-template.md
```markdown
# {Title}

> Source: {URL or origin description}
> Collected: {YYYY-MM-DD}
> Published: {YYYY-MM-DD or Unknown}

{Original content below. Preserve the source text faithfully. Clean up formatting noise, but do not rewrite opinions or alter meaning.}
```

## references/article-template.md
```markdown
# {Title}

> Sources: {Author1, YYYY-MM-DD; Author2, YYYY-MM-DD}
> Raw: [{source1}](../../raw/{topic1}/{filename1}.md); [{source2}](../../raw/{topic2}/{filename2}.md)

## Overview
{One paragraph summarizing the key points of this article.}

## {Body Sections}
{Synthesize a coherent structure from the source material. Do not copy source text verbatim; distill and reorganize. Use blockquotes sparingly for particularly important original phrasing.}

## See Also   (optional)
- Same topic: [Other Article](other-article.md)
- Different topic: [Other Article](../other-topic/other-article.md)
```

## references/archive-template.md
```markdown
# {Title}

> Sources: [{Cited Article 1}](article1.md); [{Cited Article 2}](../other-topic/article2.md)
> Archived: {YYYY-MM-DD}

## Overview
{One paragraph summarizing the query and key findings.}

## {Body Sections}
{The synthesized answer, lightly edited for wiki context. Point-in-time snapshot; never cascade-updated.}

## See Also   (optional)
```

## references/index-template.md
```markdown
# Knowledge Base Index

## {topic-name}
{One-line description of this topic.}

| Article | Summary | Updated |
|---------|---------|---------|
| [{Article Title}]({topic-name}/{article}.md) | {One-line summary} | {YYYY-MM-DD} |
| [{Archived Article}]({topic-name}/{archived}.md) | [Archived] {One-line summary} | {YYYY-MM-DD} |
```

## examples/log-sample.md (excerpt format)
Sample log entries use parseable headers:
```
## [YYYY-MM-DD] ingest | <primary article title>
- Updated: <cascade-updated article title>

## [YYYY-MM-DD] query | Archived: <page title>

## [YYYY-MM-DD] lint | <N> issues found, <M> auto-fixed
```

## Path conventions — critical
- Inside wiki/ files, **all links relative to the current file**.
- In conversation output (Claude → user), use **project-root-relative** paths.
- Raw links from `wiki/<topic>/article.md` → `../../raw/<topic>/file.md`.
- See-Also links same-topic: `other-article.md`; cross-topic: `../other-topic/other-article.md`.
- One topic subdir level only. No deeper nesting.

## Metadata dating semantics
- **Collected** — today's date when ingested.
- **Published** — source's own publication date, or `Unknown`.
- **Updated** — date the article's knowledge content last changed (NOT file mtime).
- **Archived** — today's date when archiving a query answer.
