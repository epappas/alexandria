# AGENTS.md

## Project Overview

Alexandria (`alexandria-wiki` on PyPI) is a local-first single-user knowledge engine. It accumulates gathered knowledge from 14+ source types (files, PDFs, URLs, git repos, GitHub, RSS, YouTube, Notion, HuggingFace, IMAP, Obsidian vaults, archives) and exposes it via MCP to connected AI agents.

The package name is `alexandria`, the CLI entry points are `alexandria` and `alxia` (shortcut). The Python module is `alexandria/`.

## Build and Test

```bash
# Install dependencies
uv sync --dev

# Run tests (352 tests, ~90 seconds)
uv run pytest tests/ -q

# Build wheel + sdist
./scripts/build.sh

# Publish to PyPI
./scripts/publish.sh
```

## Code Style

- Python 3.11+, typed throughout
- Favour simple code with little to no abstractions, always typed
- Functions should be under 50 lines
- Never use too many if..else cases — assert early, fail/return fast
- No emojis in code or comments
- Use `from __future__ import annotations` in every module
- Imports sorted: stdlib, third-party, local (`alexandria.`)
- Line length: 100 (configured in `pyproject.toml` via ruff)

## Testing

```bash
uv run pytest tests/                    # full suite
uv run pytest tests/test_pdf.py -v      # single file
uv run pytest tests/ -k "test_ingest"   # by name pattern
```

- Tests use real SQLite, real filesystem, real git repos — no fakes
- Zero tolerance for mocks of production functionality in tests
- Test fixtures use `tmp_path` for isolation
- Integration tests in `tests/integration/` run the CLI as a subprocess
- PDF tests require `pymupdf` (skip with `pytest.importorskip`)

## Project Structure

```
alexandria/
  cli/            # Typer CLI commands (one file per command group)
  core/           # Business logic
    adapters/     # Source adapters (local, git, github, rss, youtube, notion, etc.)
    beliefs/      # Belief revision with supersession chains
    capture/      # Conversation capture from agent sessions
    cascade/      # Wiki write operations (new page, merge, hedge)
    citations/    # Footnote parsing and quote anchor verification
    secrets/      # AES-256-GCM vault with PBKDF2
    verifier/     # Deterministic + hostile verifier
    ingest.py     # Core ingest pipeline (file, PDF, URL)
    pdf.py        # PDF text extraction via pymupdf
    web.py        # URL fetching and HTML-to-markdown
    runs.py       # Staged-write transaction state machine
    synthesis.py  # Temporal digest generation
    workspace.py  # Workspace CRUD
  daemon/         # Background scheduler with heartbeat
  db/             # SQLite connection, migrator, migrations/
  eval/           # M1-M5 quality metrics
  hooks/          # Hook installers for Claude Code, Codex
  llm/            # LLM provider abstraction (Anthropic, OpenAI, compatible)
  mcp/            # MCP server (stdio + HTTP/SSE) with 16 tools
  observability/  # Structured JSONL logger
tests/            # 352 tests, no mocks of production code
scripts/          # build.sh, push.sh, publish.sh
```

## Key Architecture Decisions

1. **No vectors, no RAG** — the agent IS the retriever. Alexandria provides FTS5 search primitives; the connected agent composes them.
2. **Filesystem is source of truth** for documents. SQLite is a materialized view for search/metadata/events.
3. **Every wiki write goes through the verifier** — citations must link to real source quotes with SHA-256 hash anchors.
4. **Beliefs are structured claims** with supersession chains, not just text. `alxia why <topic>` traces provenance.
5. **SQLite WAL mode** with `isolation_level=None` (manual transactions via `BEGIN IMMEDIATE`/`COMMIT`).

## Database

- SQLite at `~/.alexandria/state.db`
- 8 migrations in `alexandria/db/migrations/` (applied automatically)
- Migrator uses SHA-256 checksum tamper detection
- Key tables: `workspaces`, `documents`, `documents_fts`, `runs`, `wiki_beliefs`, `wiki_beliefs_fts`, `source_adapters`, `source_runs`, `events`, `events_fts`, `subscription_items`, `capture_queue`, `eval_runs`

## Environment Variables

- `ALEXANDRIA_HOME` — data directory (default: `~/.alexandria/`)
- `ALEXANDRIA_WORKSPACE` — override current workspace
- `ALEXANDRIA_VAULT_PASSPHRASE` — vault encryption passphrase

## Security

- Secret vault uses AES-256-GCM with PBKDF2-SHA256 (600k iterations)
- Path traversal protection on all file operations
- SSRF protection on RSS/URL fetching (blocks private IPs)
- Git ref validation prevents flag injection
- Session ID validation prevents path traversal in captures
- Dangerous URI schemes (javascript:, data:) stripped from markdown
- Settings files written atomically via tmp + rename

## Commit Guidelines

- Use conventional commits: `feat(component):`, `fix(component):`, `chore:`, `refactor:`
- Never add AI assistant names in commit messages
- Never use `git add -A` — stage specific files
- Commit messages should explain the why, not the what

## Deployment

```bash
# PyPI
./scripts/publish.sh

# Docker
docker build -t alexandria .
docker run -v ~/.alexandria:/data alxia init

# Docker push to GHCR
./scripts/push.sh
```
