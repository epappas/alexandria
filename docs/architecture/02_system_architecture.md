# 02 — System Architecture

> **Cites:** `research/reference/02_lucasastorian_impl.md`, `research/reference/04_atomicmemory_compiler.md`

## One-screen view

```
                      ~/.alexandria/
                      ├── config.toml
                      ├── state.db              (SQLite)
                      ├── secrets/              (encrypted creds)
                      └── workspaces/
                          ├── global/           (user general knowledge)
                          │   ├── SKILL.md
                          │   ├── raw/
                          │   └── wiki/
                          └── <project>/
                              ├── SKILL.md
                              ├── raw/
                              └── wiki/

                            ▲
                            │
             ┌──────────────┴────────────────┐
             │                               │
   ┌─────────┴─────────┐           ┌─────────┴─────────┐
   │  alexandria CLI      │           │  alexandria daemon   │   (optional)
   │                   │           │                   │
   │  init, project,   │           │  - sync scheduler │
   │  source, sync,    │           │  - subscriptions  │
   │  ingest, query,   │           │  - local web UI   │
   │  lint, export     │           │  - MCP endpoint   │
   └─────────┬─────────┘           └─────────┬─────────┘
             │                               │
             └─────────────┬─────────────────┘
                           ▼
                ┌────────────────────┐
                │  Guardian Agent    │   (Claude via MCP,
                │  (LLM client)      │    or CLI `alexandria chat`)
                └────────────────────┘
```

Three entry points, one data directory:

- **`alexandria` CLI** — the primary user surface. All operations (init, add source, sync, ingest, query, lint, export) are subcommands.
- **`alexandria mcp serve --workspace <slug>`** — a stdio MCP server. The *primary* integration path for agents: Claude Code, Cursor, Codex CLI, Windsurf, and Claude Desktop launch it as a subprocess and speak MCP over stdin/stdout. **No daemon required.** One process per session, per workspace. See `08_mcp_integration.md` for the full tool surface and client configs.
- **`alexandria daemon`** — a long-running local process. Optional. Runs scheduled syncs, polls subscriptions, serves a local web UI at `http://localhost:<port>`, and exposes MCP over HTTP+SSE (for Claude.ai web and any client that prefers network transport). Not started by default; `alexandria daemon start` enables it.

## Components

| Component | Tech | Responsibility |
|---|---|---|
| **CLI** | Python + `typer` | Init, workspace/project management, source config, sync triggers, ingest/query/lint shortcuts, export |
| **Core library** | Python 3.12+, `pydantic`, `sqlalchemy` core (or `asyncpg` for sqlite via `aiosqlite`) | Filesystem layout, SQLite schema, source adapter runtime, agent glue |
| **Daemon** | `uvicorn` + `fastapi` + `apscheduler` | Scheduled syncs, subscription polling, web UI, MCP server |
| **Web UI** | Server-rendered HTML (Jinja) or a small HTMX interface | Dashboard, source status, wiki viewer, subscription inbox. No write surface — agent-only. |
| **MCP server** | `fastmcp` | Tools the agent calls: `guide`, `search`, `read`, `write`, `delete`, `sources`, `subscriptions`, `history`. Runs as stdio subprocess or HTTP via the daemon — same code, two transports. |
| **State store** | SQLite (`~/.alexandria/state.db`) | Source adapters, sync runs, subscription queues, search indexes, provenance, structured log |
| **Object storage** | Filesystem under `raw/` | PDFs, images, originals. Large blobs live next to their metadata. |

One process per entry point (CLI invocation or daemon). Both share the same SQLite file; WAL mode keeps concurrent reads + occasional writes safe.

## Why SQLite + filesystem instead of Postgres

- **Personal tool.** Zero ops. No services to run. No containers to start. `pip install alexandria && alexandria init` and you're done.
- **Files are the primary artifact.** The user can `git init ~/.alexandria/workspaces/customer-x`, open it in Obsidian, back it up with Dropbox. SQLite stays consistent because it's a derivative — rebuildable from the filesystem.
- **Search works.** SQLite FTS5 covers keyword search up to several thousand pages per workspace. Combined with `grep` (regex) and `list` (glob) primitives, it gives the agent everything it needs to navigate without an embedding pipeline.
- **No tenancy to enforce.** No RLS, no `user_id` columns, no scoping middleware. The only boundary is **workspace** — which is literally a directory path.

## Why a daemon is optional

Everything the daemon does, the CLI can also do on demand (`alexandria sync`, `alexandria subscriptions poll`, `alexandria query`). The daemon exists to enable:
- Scheduled syncs (cron every N minutes).
- Newsletter/Twitter polling.
- Live web UI.
- MCP endpoint for Claude/Cursor.

Users who don't want a background process can skip it and run everything from the CLI. The daemon is the same Python code, just invoked by `apscheduler` on a timer and served over HTTP.

## Request flow examples

### `alexandria init`
```
alexandria init [--path ~/.alexandria]
  ↓
Creates ~/.alexandria/{config.toml, state.db, secrets/, workspaces/global/}
Creates workspaces/global/{SKILL.md, raw/, wiki/}
Seeds wiki/overview.md, wiki/index.md, wiki/log.md with starter content
Runs SQLite migrations
```

### `alexandria project create customer-acme`
```
Creates workspaces/customer-acme/{SKILL.md, raw/, wiki/}
Inserts workspaces row in SQLite
Prompts user for description
Seeds structural files
```

### `alexandria source add --workspace customer-acme --type notion`
```
Prompts for Notion integration token, database IDs
Stores encrypted config in secrets/ and source_adapters row in SQLite
Does NOT sync yet — prints next step: `alexandria sync customer-acme`
```

### `alexandria sync customer-acme`
```
Finds all source_adapters for the workspace
Runs each adapter's list → fetch cycle
Writes new/updated files to workspaces/customer-acme/raw/<adapter>/...
Records source_run row in SQLite with counts
Updates FTS5 index on new content
Prints summary: "Notion: 12 new, 3 updated. GitHub: 2 new."
```

### User asks the agent to ingest
The agent is running in Claude.ai (or `alexandria chat`) and connected to the MCP endpoint (`alexandria daemon start` made it available). User says "ingest the new Notion pages."
```
Agent → guide(workspace="customer-acme") — reads current state
Agent → search(path="/raw/notion/*") — finds pending items
Agent → read(...) for each
Agent → write(create/append/str_replace) for wiki pages
Agent → write(append) to log.md
```

Every call lands on the local daemon, which writes directly to the workspace files and updates SQLite.

## Deployment shape

There is no deployment. It's a local Python package:

```
pip install alexandria           # or: pipx install alexandria
alexandria init                  # creates ~/.alexandria/
alexandria project create ...    # optional
alexandria source add ...
alexandria daemon start          # optional: web UI + MCP + scheduler
```

For power users: `alexandria export --workspace X --format obsidian-zip` produces a portable artifact.

## Language and stack choices

- **Python 3.12+** — user's required language.
- **`typer`** — CLI with good typing and help text.
- **`fastapi` + `uvicorn`** — daemon HTTP surface.
- **`fastmcp`** — MCP server inside the daemon.
- **`apscheduler`** — in-process scheduler for syncs and subscriptions.
- **`aiosqlite` + `sqlite-utils`** — SQLite access. FTS5 for search.
- **`anthropic` / `openai` / `google-genai` / provider SDKs** (optional) — only needed for daemon-owned scheduled synthesis and CLI batch operations. Interactive work happens in the MCP client which brings its own provider. See `11_inference_endpoint.md`.
- **`pydantic`** — config + data shapes.
- **`cryptography`** — encrypted secrets storage (symmetric key derived from OS keyring).

Dev tooling: `mypy --strict`, `pytest`, `pytest-asyncio`.

## Concurrency model

The daemon is a single asyncio process. Concurrent source syncs run as asyncio tasks with per-adapter locks. SQLite writes are serialized through a write lock; reads are concurrent. The CLI and daemon may run at the same time because both use WAL mode — conflicts are rare and detected via `busy_timeout`.

Long-running sync jobs are moved off the main loop into a worker thread pool when they hit blocking I/O (git clone, large PDF extraction). LLM calls stay on the main loop; they're I/O bound.

## What this model does NOT do

- No account system.
- No cloud backend.
- No shared wikis across machines (unless the user syncs `~/.alexandria/` with Syncthing or git themselves — explicitly supported but not managed by us).
- No cross-workspace queries at MVP.
- No server-side agent runs scheduled by us. (The daemon *can* schedule background lint, but it still talks to a local LLM — no remote compute.)

See `03_workspaces_and_scopes.md` for the workspace model, `05_source_integrations.md` for adapters, `06_data_model.md` for the on-disk layout + SQLite schema.
