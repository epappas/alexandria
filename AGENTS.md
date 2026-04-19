# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, Cursor, Copilot) when working with code in this repository.

## Project Overview

Alexandria (`alexandria-wiki` on PyPI) is a local-first single-user knowledge engine. It accumulates gathered knowledge from 14+ source types (files, PDFs, URLs, git repos, GitHub, RSS, YouTube, Notion, HuggingFace, IMAP, Obsidian vaults, archives) and exposes it via MCP to connected AI agents.

The package name is `alexandria`, the CLI entry points are `alexandria` and `alxia` (shortcut). The Python module is `alexandria/`.

## Build & Test Commands

```bash
uv sync --dev                              # install dependencies
uv run pytest tests/ -q                    # full suite (352 tests, ~90s)
uv run pytest tests/test_pdf.py -v         # single file
uv run pytest tests/ -k "test_ingest"      # by name pattern
uv run pytest tests/integration/ -v        # integration tests (subprocess CLI)
./scripts/build.sh                          # test + build sdist + wheel + twine check
./scripts/publish.sh                        # test + build + upload PyPI + git tag
```

## Code Style

- Python 3.11+, typed throughout, strict mypy
- Favour simple code with little to no abstractions, always typed
- Functions should be under 50 lines
- Never use too many if..else cases — assert early, fail/return fast
- No emojis in code or comments
- Use `from __future__ import annotations` in every module
- Imports sorted: stdlib, third-party, local (`alexandria.`)
- Line length: 100 (configured in `pyproject.toml` via ruff)

## Testing

- Tests use real SQLite, real filesystem, real git repos — no fakes
- Zero tolerance for mocks of production functionality
- Test fixtures use `tmp_path` for isolation
- Integration tests in `tests/integration/` run the CLI as a subprocess
- PDF tests require `pymupdf` (skip with `pytest.importorskip`)

## Architecture

Alexandria is a local-first knowledge engine with three entry points: CLI (`alxia`), MCP server (stdio + HTTP), and background daemon. All three share the same SQLite database and filesystem.

### The Write Path (ingest pipeline)

Every wiki write follows this exact sequence through `alexandria/core/ingest.py`:

1. Read source (text, PDF via `core/pdf.py`, URL via `core/web.py`, code via `core/code.py`, conversation via `core/capture/`)
2. **Dedup check** — content hash compared against `documents` table. Unchanged files return immediately with zero overhead.
3. Copy to `raw/local/` with SHA-256 dedup (collision appends `-2`, `-3`, etc.)
4. Create a **Run** (5-state machine: pending, verifying, committed, rejected, abandoned)
4. Stage wiki page in `~/.alexandria/runs/<run_id>/staged/` with citations
5. Run `DeterministicVerifier` — checks footnotes, quote anchors (SHA-256 hashes), source existence
6. Verdict must be exactly `"commit"` to proceed; anything else triggers rejection
7. `commit_run()` validates every staged path stays within `wiki/` boundary (path traversal protection), then copies to live wiki

Runs persist on disk as `{meta.json, staged/, verifier/, status}`. The status file is a plain text enum value.

### Database Pattern

SQLite with `isolation_level=None` (autocommit mode). All transactions are explicit:

```python
conn.execute("BEGIN IMMEDIATE")
try:
    conn.execute(...)
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
```

The migrator (`db/migrator.py`) uses `executescript()` for DDL (which auto-commits), then records metadata in a separate `BEGIN IMMEDIATE`/`COMMIT` block. All DDL uses `IF NOT EXISTS` for idempotency. Migrator checksums every applied migration with SHA-256 and refuses to proceed on tampering.

- SQLite at `~/.alexandria/state.db`
- 10 migrations in `alexandria/db/migrations/` (applied automatically)
- Key tables: `workspaces`, `documents`, `documents_fts`, `runs`, `wiki_beliefs`, `wiki_beliefs_fts`, `source_adapters`, `source_runs`, `events`, `events_fts`, `subscription_items`, `capture_queue`, `eval_runs`

### MCP Server

Two binding modes in `mcp/server.py`:
- **Open mode** (`alxia mcp serve`): all workspaces accessible, every tool requires explicit `workspace` argument
- **Pinned mode** (`alxia mcp serve --workspace <slug>`): locked to one workspace, other values rejected

20 tools registered in `mcp/tools/`. Each tool is a module with a `register(mcp, resolve_workspace)` function.

Navigation: `guide`, `overview`, `list`, `grep`, `search`, `read`, `follow`, `history`, `why`, `timeline`, `events`, `sources`, `subscriptions`, `git_log`, `git_show`, `git_blame`.
Write: `ingest` (files, dirs, URLs, repos, conversations), `belief_add`, `belief_supersede`, `query`.

### Source Adapters

All adapters in `core/adapters/` implement the same sync pattern: `sync(workspace_path, config) -> tuple[list[FetchedItem], SyncResult]`. The sync orchestrator (`core/adapters/sync.py`) coordinates rate limiter, circuit breaker, event storage, and run tracking.

### Key Architecture Decisions

1. **No vectors, no RAG** — the agent IS the retriever. Alexandria provides FTS5 search primitives; the connected agent composes them.
2. **Filesystem is source of truth** for documents. SQLite is a materialized view for search/metadata/events.
3. **Every wiki write goes through the verifier** — citations must link to real source quotes with SHA-256 hash anchors.
4. **Beliefs are structured claims** with supersession chains, not just text. `alxia why <topic>` traces provenance.
5. **Hybrid search** — BM25 (55%) + recency decay (30%) + belief support (15%) for composite scoring.
6. **AST extraction** — Python, TypeScript, Rust, Go, Terraform, Ansible, YAML parsed into structured beliefs.
7. **Conversation capture** — Claude Code JSONL sessions ingested with artifact extraction (papers, repos).
8. **Self-awareness** — Alexandria can answer queries about its own state, capabilities, and ingested content.
9. **Document dedup** — content-hash check skips re-ingest of unchanged files with zero overhead.
10. **Belief integrity** — supersede-all-then-restore pattern prevents duplicates on re-ingest. `alxia beliefs cleanup` removes orphans and deduplicates.

### Setup for Claude Code

```bash
pip install alexandria-wiki           # or: uv pip install alexandria-wiki
alxia init                            # creates ~/.alexandria/
alxia mcp install claude-code         # registers MCP server
alxia hooks install claude-code       # auto-captures conversations on session end
```

Restart Claude Code. Alexandria tools appear as `mcp__alexandria__*`.

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
  daemon/         # Background scheduler with heartbeat
  db/             # SQLite connection, migrator, migrations/
  eval/           # M1-M5 quality metrics
  hooks/          # Hook installers for Claude Code, Codex
  llm/            # LLM provider abstraction (Anthropic, OpenAI, compatible)
  mcp/            # MCP server (stdio + HTTP/SSE) with 20 tools
  observability/  # Structured JSONL logger
tests/            # 352+ tests, no mocks of production code
scripts/          # build.sh, push.sh, publish.sh
```

## Key Constraints

- **Never claim something works unless you have validated it and shown evidence.** Run the code, check actual output, verify database state, confirm files on disk. If you cannot test it (e.g. LLM path inside a Claude Code session), say so explicitly. Be ready to vouch for every result you report as delivered. Claims affect SLOs/SLA contracts and may be used as legal evidence — 100% accuracy required.
- **Zero tolerance for stubs/fakes/mocks/TODOs/placeholders** in production code. Tests use real SQLite, real filesystem, real git repos.
- **Every function under 50 lines.** Assert early, return fast. No deep if/else nesting.
- **Typed throughout.** Every module starts with `from __future__ import annotations`.
- **No emojis** in code, comments, or commit messages.
- **Never `git add -A`** — stage specific files.
- **Never add AI assistant branding** in commit messages.
- Conventional commits: `feat(component):`, `fix(component):`, `chore:`, `refactor:`

## Non-obvious Gotchas

- `executescript()` auto-commits any pending transaction. The migrator handles this by separating DDL execution from metadata INSERT.
- `connect()` returns a context manager that sets `row_factory = sqlite3.Row`. Queries return Row objects, not tuples.
- PDF citations reference the extracted `.md` file (not the binary `.pdf`) so the verifier can read and validate quote anchors.
- Workspace slugs are strictly validated: `^[a-z0-9][a-z0-9_-]{0,62}$`. Invalid input raises immediately.
- The `source_adapters` table has a CHECK constraint listing valid adapter types. Adding a new adapter type requires updating this constraint in `0004_sources.sql`.
- FTS5 queries must use the full table name in `WHERE table MATCH ?` — aliases don't work reliably.
- Integration tests run `python -m alexandria` as a subprocess, not the entry point, to avoid pip install dependency.

## Environment Variables

- `ALEXANDRIA_HOME` — data directory (default: `~/.alexandria/`)
- `ALEXANDRIA_WORKSPACE` — override current workspace slug
- `ALEXANDRIA_VAULT_PASSPHRASE` — vault encryption key (required for secrets commands)

## Security

- Secret vault uses AES-256-GCM with PBKDF2-SHA256 (600k iterations)
- Path traversal protection on all file operations
- SSRF protection on RSS/URL fetching (blocks private IPs)
- Git ref validation prevents flag injection
- Dangerous URI schemes (javascript:, data:) stripped from markdown
- Settings files written atomically via tmp + rename

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
