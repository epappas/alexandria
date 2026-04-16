# Source: atomicmemory/llm-wiki-compiler (GitHub repo)
URL: https://github.com/atomicmemory/llm-wiki-compiler
Fetched: 2026-04-15
Status: Fetched via WebFetch (README-level extraction)

---

# LLM Wiki Compiler: Project Overview

## Core Purpose
The llm-wiki-compiler transforms raw sources into a structured, interlinked markdown wiki. As stated in the README, it "Compile[s] raw sources into an interlinked markdown wiki," drawing inspiration from Karpathy's LLM Wiki pattern where knowledge is compiled once into a persistent artifact rather than re-discovered at query time.

## Key Distinction from RAG
The project positions itself as complementary to Retrieval-Augmented Generation (RAG). While RAG retrieves chunks dynamically (query → search → answer → forget), alexandria follows a different flow: "sources → compile → wiki → query → save → richer wiki → better answers." Saved query results become new wiki pages that enhance future answers.

## Architecture & Pipeline
Two-phase pipeline:
- **Phase 1**: Extract concepts from all sources
- **Phase 2**: Generate wiki pages with wikilink resolution

Design eliminates order-dependence and catches failures before writing. Incremental processing uses SHA-256 hash checking to skip unchanged sources.

## Primary Commands

| Command | Function |
|---------|----------|
| `alexandria ingest <url\|file>` | Fetch URLs or copy local files into `sources/` |
| `alexandria compile` | Extract concepts and generate pages incrementally |
| `alexandria query "question"` | Query the compiled wiki |
| `alexandria query "question" --save` | Answer and save result as a new page |
| `alexandria lint` | Validate wiki quality |
| `alexandria watch` | Auto-recompile on source changes |

## Output Structure
```
wiki/
  concepts/     (one .md file per concept with YAML frontmatter)
  queries/      (saved query answers, included in index)
  index.md      (auto-generated table of contents)
```

Pages are Obsidian-compatible, using `[[wikilinks]]` for concept references. Source attribution appears in YAML frontmatter and paragraph-level markers (`^[filename.md]`).

## Top-Level Repository Contents
**Directories:** `.github/workflows`, `docs/images`, `examples/basic`, `scripts`, `src`, `test`
**Key Files:** `package.json`, `tsconfig.json`, `tsup.config.ts`, `vitest.config.ts`, `.fallowrc.json`, `.gitignore`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `LICENSE`

## Technology Stack
- **Language**: TypeScript (99.6% of codebase)
- **Runtime**: Node.js >= 18 required
- **LLM Provider**: Currently Anthropic-only (API key required)

## Current Limitations
Acknowledged as early software, best suited for small high-signal corpora (roughly a dozen sources). Source truncation is transparently marked in frontmatter when content exceeds character limits.
