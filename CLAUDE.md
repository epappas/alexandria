# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
uv run pytest tests/ -q                    # full suite (352 tests, ~90s)
uv run pytest tests/test_pdf.py -v         # single file
uv run pytest tests/ -k "test_ingest"      # by name pattern
uv run pytest tests/integration/ -v        # integration tests (subprocess CLI)
./scripts/build.sh                          # test + build sdist + wheel + twine check
./scripts/publish.sh                        # test + build + upload PyPI + git tag
```

## Architecture

Alexandria is a local-first knowledge engine with three entry points: CLI (`alxia`), MCP server (stdio + HTTP), and background daemon. All three share the same SQLite database and filesystem.

### The Write Path (ingest pipeline)

Every wiki write follows this exact sequence through `alexandria/core/ingest.py`:

1. Read source (text, PDF via `core/pdf.py`, or URL via `core/web.py`)
2. Copy to `raw/local/` with SHA-256 dedup (collision → append `-2`, `-3`, etc.)
3. Create a **Run** (5-state machine: pending → verifying → committed | rejected | abandoned)
4. Stage wiki page in `~/.alexandria/runs/<run_id>/staged/` with citations
5. Run `DeterministicVerifier` — checks footnotes, quote anchors (SHA-256 hashes), source existence
6. Verdict must be exactly `"commit"` to proceed; anything else → rejection
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

### MCP Server

Two binding modes in `mcp/server.py`:
- **Open mode** (`alxia mcp serve`): all workspaces accessible, every tool requires explicit `workspace` argument
- **Pinned mode** (`alxia mcp serve --workspace <slug>`): locked to one workspace, other values rejected

16 tools registered in `mcp/tools/`. Each tool is a module with a `register(mcp, resolve_workspace)` function.

### Source Adapters

All adapters in `core/adapters/` implement the same sync pattern: `sync(workspace_path, config) -> tuple[list[FetchedItem], SyncResult]`. The sync orchestrator (`core/adapters/sync.py`) coordinates rate limiter, circuit breaker, event storage, and run tracking.

### Beliefs

Structured claims extracted from wiki pages at write time. Each belief has a supersession chain (belief A superseded by belief B). Query via `alxia why <topic>` traces provenance through footnotes to raw sources.

## Key Constraints

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
