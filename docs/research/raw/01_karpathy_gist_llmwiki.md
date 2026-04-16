# Source: Karpathy's Original LLM Wiki Gist
URL: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
Fetched: 2026-04-15
Status: Fetched via WebFetch (summarized extraction)

---

## File: llm-wiki.md

### Main Document Structure

**LLM Wiki** — A pattern for building personal knowledge bases using LLMs.

This is intentionally abstract documentation meant to be shared with your LLM agent (Claude Code, OpenAI Codex, etc.) for collaborative instantiation based on your specific needs.

### Core Concept

Rather than traditional RAG (retrieve-augment-generate) where documents are indexed for query-time retrieval, the pattern proposes that "the LLM **incrementally builds and maintains a persistent wiki**" — a structured markdown collection that sits between raw sources and the user, with knowledge compiled once and kept current rather than re-derived per query.

### Three-Layer Architecture

1. **Raw sources** — Immutable curated documents (articles, PDFs, images); LLM reads but never modifies
2. **The wiki** — LLM-generated markdown files with summaries, entity pages, concept pages; LLM owns this entirely
3. **The schema** — Configuration document (CLAUDE.md or AGENTS.md) defining structure, conventions, and workflows

### Key Operations

- **Ingest**: Process new sources; LLM reads, discusses takeaways, writes summaries, updates index and relevant pages
- **Query**: Ask questions against wiki; LLM searches pages, synthesizes answers; valuable answers filed back as new wiki pages
- **Lint**: Health-check wiki for contradictions, stale claims, orphan pages, missing cross-references

### Special Files

**index.md** — Content-oriented catalog listing all pages with links, one-line summaries, organized by category

**log.md** — Append-only chronological record with parseable entries (e.g., `## [2026-04-02] ingest | Article Title`)

### Optional Tools

- Web Clipper for converting articles to markdown
- Local image downloads for Obsidian
- Obsidian graph view for visualization
- qmd for local search with BM25/vector hybrid search
- Marp for markdown-based presentations
- Dataview plugin for YAML frontmatter queries

### Why This Works

"The tedious part of maintaining a knowledge base is not the reading or the thinking — it's the bookkeeping." LLMs don't tire, forget updates, or lose consistency across multiple files. Humans curate sources and ask questions; LLMs handle maintenance.

### Design Philosophy

The pattern relates to Vannevar Bush's Memex concept (1945) — personal, curated knowledge with valued connections between documents — but addresses the maintenance burden Bush couldn't solve.

---

## Notable Discussion Points from Comments

The gist generated 500+ comments with significant debate:

**Support**: Users reported success building wikis with compounding knowledge, notably one user with "almost no modifications" completing a 200-page wiki from 35 sources in approximately one hour.

**Criticism**: Several commenters raised concerns about scalability, hallucination risks, maintenance burden actually increasing rather than decreasing, and the fundamental architectural mismatch between markdown files and true knowledge management requiring actual database structures with foreign keys and schemas.

**Extensions**: Community members presented implementations including OmegaWiki, Synthadoc, Graphite Atlas, AIOS, and AgentWiki — each adding typed entities, graph databases, or automation layers to address limitations.
