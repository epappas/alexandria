# Source: Astro-Han/karpathy-llm-wiki (GitHub repo — Agent Skill)
URL: https://github.com/Astro-Han/karpathy-llm-wiki
Fetched: 2026-04-15
Status: Fetched via WebFetch (README-level extraction)

---

# karpathy-llm-wiki Repository Overview

## What It Is
A reusable Agent Skills-compatible tool that implements Karpathy's LLM Wiki concept. It enables coding agents (Claude Code, Cursor, Codex) to build and maintain structured knowledge bases from raw sources, with synthesis, citations, and automated linting.

## Top-Level Structure
```
karpathy-llm-wiki/
├── assets/           (Images and visual resources)
├── examples/         (Sample wiki pages and operation logs)
├── references/       (Supporting documentation)
├── .gitignore
├── LICENSE          (MIT)
├── README.md
└── SKILL.md         (Full skill specification)
```

## Core Concept: LLM Wiki vs RAG
The project distinguishes itself from RAG systems. Rather than retrieving and synthesizing raw chunks at query time, an LLM wiki maintains "curated markdown pages" where knowledge synthesis occurs during ingestion, enabling compounding knowledge over time.

## Three Main Operations

| Operation | Purpose | Output |
|-----------|---------|--------|
| **Ingest** | Collect sources into `raw/` and compile into wiki | New/updated wiki pages |
| **Query** | Search wiki and answer with citations | Grounded answers with markdown links |
| **Lint** | Verify index integrity and cross-references | Auto-fixes and issue reports |

## Knowledge Base Directory Convention
```
your-project/
├── raw/          (Immutable source materials)
│   └── topic/
│       └── 2026-04-03-source-article.md
├── wiki/         (LLM-maintained compiled knowledge)
│   ├── topic/
│   │   └── concept-name.md
│   ├── index.md  (Global table of contents)
│   └── log.md    (Append-only operation record)
```

## Installation
```bash
npx add-skill Astro-Han/karpathy-llm-wiki
```

## Production Track Record
The skill derives from "a real knowledge base with 94 articles and 99 sources maintained daily since April 2026," demonstrating battle-tested workflow patterns.

## License
MIT
