# Alexandria

Local-first single-user knowledge engine. Accumulates your gathered knowledge (raw sources, compiled wiki pages, beliefs, AI conversations) and exposes it via MCP to connected agents like Claude Code for query, retrieval, and synthesis.

## Quick Start

```bash
pip install "alexandria-wiki[all]"
alxia init
alxia mcp install claude-code
alxia hooks install claude-code
```

Restart Claude Code. Alexandria tools are now available.

## What Alexandria Does

- **Ingest** files, directories, URLs, git repos, PDFs, code, conversations
- **Search** with hybrid BM25 + recency + belief support scoring
- **Query** natural language questions with LLM-powered grounded answers
- **Track beliefs** as structured claims with supersession chains and provenance
- **Extract code structure** from Python, TypeScript, Rust, Go, Terraform, Ansible, YAML
- **Capture conversations** from Claude Code sessions with artifact extraction
- **Merge concepts** automatically when multiple sources cover the same topic
- **Cross-reference** related wiki pages with auto-discovered See Also links

## Architecture

- **No vectors, no RAG** -- the agent IS the retriever
- **Filesystem is source of truth** -- SQLite is a materialized view
- **Every wiki write goes through a verifier** -- citations must link to real sources
- **Beliefs are structured claims** with supersession chains, not just text
- **Hybrid search** -- FTS5 BM25 + recency decay + belief support

## Learn More

- [Getting Started](guide.md) -- full user guide
- [CLI Reference](cli.md) -- all commands
- [Architecture](architecture/README.md) -- design documents
