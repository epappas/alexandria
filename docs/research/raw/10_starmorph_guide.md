# Source: Starmorph Blog — "How to Build Karpathy's LLM Wiki: The Complete Guide"
URL: https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide
Fetched: 2026-04-15
Status: Fetched via WebFetch (summarized extraction)

---

# LLM Wiki Guide Summary

## Core Architecture
Three layers:
1. **Raw Sources** (`raw/`) — Immutable input documents that serve as verification baseline
2. **Wiki Output** (`wiki/`) — LLM-generated markdown organized by type (concepts, entities, sources, comparisons)
3. **Schema Configuration** (`CLAUDE.md`) — Defines structure, naming conventions, and workflows

## Three Core Operations
**Ingest:** Process new sources by creating summaries, updating related pages, and maintaining the index.
**Query:** Ask questions against the wiki; the LLM navigates via index rather than loading everything into context.
**Lint:** Periodic health checks for contradictions, orphan pages, missing concepts, and stale claims.

## Setup Steps
1. Create directory structure with `raw/`, `wiki/`, and `outputs/` subdirectories
2. Initialize Git for version control
3. Create `CLAUDE.md` schema file
4. Add source documents to `raw/`
5. Use Claude Code to ingest and generate wiki pages

## Key Distinction: LLM Wiki vs RAG
The article states: "The LLM Wiki is essentially a manual, traceable implementation of Graph RAG." It works best for personal/team-scale knowledge (under 100-200 sources), while RAG suits enterprise-scale deployments with millions of documents.

## Recommended Tooling
- Claude Code (LLM agent)
- Obsidian (frontend with graph visualization)
- QMD (semantic search via BM25 + vector + LLM re-ranking)
- Git (version control)
- Obsidian Web Clipper (source conversion)

The pattern emerged from addressing why knowledge bases collapse — the maintenance burden exceeds human capacity at scale.
