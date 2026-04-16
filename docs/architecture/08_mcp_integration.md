# 08 — MCP Integration

> **Cites:** `research/reference/02_lucasastorian_impl.md`, `research/reference/03_astrohan_skill.md`

`alexandria` is a **first-class MCP server**. The guardian agent runs inside any MCP-capable client (Claude Code, Claude Desktop, Claude.ai, Cursor, Codex CLI, Windsurf, Zed, Continue, any future client) and uses `alexandria`'s tools to read, search, and write wiki content. No custom client, no lock-in.

MCP is not just our integration story — it is how retrieval *works* in an agentic world. From the user's own reference gist (`research/raw/26_*`):

> *"Anthropic's Model Context Protocol unifies all retrieval modalities under a single tool-call interface... retrieval is no longer a pipeline stage — it is one tool among many that the agent calls when it decides it needs information. The agent controls when, what, and from where to retrieve, rather than retrieval being a mandatory pre-generation step."*

alexandria takes this seriously. We are *one of several* retrieval tools an agent composes in a session. Our tool descriptions are written to be distinguishable from web search, code search, and other wiki servers the agent may have registered. Our workspace-per-instance binding keeps boundaries clear. Our logs are structured so multi-tool sessions are debuggable.

This document specifies the transports, the per-workspace binding, the tool surface, and the exact client configs.

## Two transports, one codebase

| Transport | When | Who starts it | Daemon needed? |
|---|---|---|---|
| **stdio** | Local agents (Claude Code, Cursor, Codex CLI, Windsurf, Claude Desktop) | The client launches `alexandria` as a subprocess | No |
| **HTTP + SSE** | Remote agents (Claude.ai web, shared workstations), web UI | The daemon listens on `localhost:<port>` | Yes |

Both transports expose the same tools, operate on the same workspace binding, and use the same `fastmcp` registration code. The only difference is how the server is invoked.

### stdio (primary)

```bash
alexandria mcp serve                       # open mode — all workspaces available
alexandria mcp serve --workspace <slug>    # pinned mode — locked to one workspace
```

- Reads MCP messages from stdin, writes to stdout.
- Logs to stderr only (stdout is the MCP channel — writing to it corrupts the protocol).
- The process lifetime is one MCP session. The client launches a new process per session.
- No network binding. Zero attack surface beyond the client that launched it.
- **No authentication needed** — trust is at the OS-user level. Whoever can launch `alexandria` as this user already has access to `~/.alexandria/`.

This is the natural mode for local coding agents. Claude Code / Cursor / Codex all expect to launch MCP servers as subprocesses.

### HTTP + SSE (secondary)

```bash
alexandria daemon start
# serves http://localhost:<port>/mcp/<workspace>
```

- Daemon runs `fastmcp`'s streamable HTTP transport.
- One endpoint per workspace. The URL pins the binding.
- Bound to `127.0.0.1` only by default. `--bind 0.0.0.0` requires an explicit flag plus a bearer token.
- Optional bearer-token auth (stored in `~/.alexandria/config.toml`) for clients that want defense-in-depth. Off by default on loopback.

This mode enables Claude.ai's web connector, per-workspace URLs that Cursor can pin, and the local web UI's built-in chat.

## Workspace binding — open and pinned modes

The server has two modes, selected at launch. The tool schema is the same in both; only the validation differs.

### Open mode — the default

```bash
alexandria mcp serve
```

- Every tool requires an explicit `workspace` argument.
- The agent calls `guide()` (no argument) first and receives the list of available workspaces + their current state.
- The agent then passes a workspace slug on every subsequent call: `search(workspace="customer-acme", ...)`, `write(workspace="global", ...)`, etc.
- Cross-workspace **reads** are permitted within a session. Cross-workspace **writes** are fine — each write is atomic to one workspace.
- This is the frictionless default: one MCP server registration, every workspace accessible.

### Pinned mode — for project-scoped safety

```bash
alexandria mcp serve --workspace customer-acme
```

- The server is locked to `customer-acme`. Tools can omit `workspace` (it defaults to the pinned slug) or pass `workspace="customer-acme"` explicitly.
- Any tool call passing a different slug is rejected with `workspace_not_accessible`.
- `guide()` returns only the pinned workspace's state.
- Use this when a project-level `.mcp.json` should not be able to reach the user's global wiki. The boundary is a launch-time promise: once the subprocess starts, it cannot escape.

### Which mode to use where

| Situation | Mode | Why |
|---|---|---|
| Default Claude Code / Cursor / Claude Desktop registration | Open | One entry, all workspaces. Agent picks per task. |
| Project-scoped `.mcp.json` checked into a repo | Pinned | The repo is Acme-related; the wiki should be too. |
| Shared workstation with distinct client sessions | Pinned | Each session holds its own trust boundary. |
| Codex CLI / Windsurf global config | Open | Same reason as Claude Code. |
| Claude.ai web connector | Pinned, via the daemon's `/mcp/<slug>` URL | The URL pins the boundary. |

### Concurrent writers — what happens when two clients bind the same workspace

**Closes:** `research/reviews/01_llm_architect.md` §2.7.

alexandria is single-user, but a single user routinely runs multiple MCP clients at once (Claude Code in one terminal, Claude Desktop in the menu bar, Cursor in a project repo). All three may bind the same workspace and try to invoke `write` simultaneously. Three layers of serialization make this safe:

1. **SQLite WAL mode.** Two writes to the runs / wiki_log_entries / events tables get serialized at the database layer; neither corrupts the other. Concurrent reads remain non-blocking.
2. **Per-workspace file lock.** Before any staged-run commit (the moment a `runs/<run_id>/staged/` directory is moved into the live `wiki/`), the writer acquires `~/.alexandria/workspaces/<slug>/.lock` via `fcntl` advisory locking. The lock is held only during the move + git-commit + SQLite-state-flush — typically under 100 ms. Other writers wait up to 30 seconds.
3. **`workspace_busy` error past the timeout.** If a writer cannot acquire the lock within 30 seconds, the MCP tool returns `workspace_busy` with the holding run_id. The caller decides whether to retry or surface to the user. **First writer wins, second waits or fails loud — never silent races.**

Stage-only operations (writing into `runs/<run_id>/staged/`) do **not** require the lock — only the commit does. This means two clients can plan and stage in parallel; only the final move is serialized. In practice, contention is rare because the lock window is tiny and most writes are read-heavy.

For interactive cross-client conflict (Claude Code and Cursor both editing related pages in the same minute), the `15_cascade_and_convergence.md` workflow's `stale_plan` reject handles the case: the second writer's plan is built against a wiki state that no longer exists post-first-commit, the verifier catches it, and the second writer re-plans. Loud failure, no corruption.

### Caller capability assumption

**Closes:** `research/reviews/01_llm_architect.md` §2.1b (the runtime caller-capability dependency).

The agent-as-retriever charter (`research/reference/12_agentic_retrieval.md`) assumes the connected MCP client is running a model with **≥ 128K context** and **reliable tool-use discipline**. Models that do not meet this bar will navigate alexandria's tool surface poorly — they will burn turns, miss cascade opportunities, and skip the `overview` shortcut.

**Known to meet the bar at MVP** (verified via `14_evaluation_scaffold.md`'s capability floor test):

- Claude Code (Anthropic Opus 4.x / Sonnet 4.x)
- Claude Desktop (same)
- Claude.ai web (same)
- Cursor agent mode (Anthropic or GPT-5 frontier)
- Codex CLI (GPT-5 frontier)

**Known to fail or degrade** without the floor test passing:

- Models below 30B parameters via OpenAI-compatible endpoints (Ollama, LM Studio) — tool use is often unreliable.
- Older GPT-3.5 / Claude 3 Haiku / Gemini Pro 1.5 — context window or tool discipline insufficient for cascade workflows.
- Anything not explicitly tested via `alexandria eval floor --preset <preset>`.

The architecture **does not stop working** below the floor — it fails silently, which `14_evaluation_scaffold.md`'s daemon-startup warning catches. Users running below the floor see the warning, see their M1/M2 scores degrade, and decide whether to upgrade their model preset or accept reduced quality.

### Why `workspace` is always in the schema

Keeping `workspace` on every tool schema — even in pinned mode — means:
- One tool signature across both modes; the agent learns it once.
- The same registered server can be consulted from multiple chats without confusion.
- Logs always carry the workspace dimension, no "implicit" calls.

## Tool surface

Defined in `04_guardian_agent.md`. Briefly:

| Tool | Purpose |
|---|---|
| `guide` | Onboarding. Returns schema + current state + self-awareness summary. Called first. |
| `search` | `list` (glob) or `search` (FTS5). Raw and wiki layers. |
| `read` | Single file, glob batch, PDF page ranges, optional images. |
| `write` | `create`, `str_replace`, `append`. Validates citations. Rejects writes to raw/. |
| `delete` | Soft-delete to `.trash/`. Protects structural files. |
| `sources` | List configured source adapters + sync state + pending-to-ingest counts. Read-only. |
| `subscriptions` | List pending subscription items. Read-only. |
| `history` | Structured query over `wiki_log_entries`. The self-awareness accessor. |

Every tool accepts a `workspace: str` argument. In open mode it is required; in pinned mode it defaults to the pinned slug and rejects any other value. All tool calls are scoped to exactly one workspace — there is no single call that reads from workspace A and writes to workspace B.

## Client setup — exact configs

### Claude Code (Anthropic CLI)

**Default registration — open mode, all workspaces:**
```bash
claude mcp add alexandria -- alexandria mcp serve
```

**Project-scoped `.mcp.json` — pinned to one workspace for this repo:**
```json
{
  "mcpServers": {
    "alexandria": {
      "command": "alexandria",
      "args": ["mcp", "serve", "--workspace", "customer-acme"]
    }
  }
}
```
Drop this at the project root. Every `claude` session launched from that directory is locked to `customer-acme` — the agent cannot reach the user's global wiki from that session.

Both styles can coexist: a user-level open-mode registration for general use, overridden per-project by a checked-in pinned `.mcp.json`.

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "alexandria": {
      "command": "alexandria",
      "args": ["mcp", "serve"]
    }
  }
}
```

Restart Claude Desktop. The tools appear under the connector menu. Claude Desktop is general-purpose, so open mode is the right default — add `--workspace <slug>` to the args array if you want to pin it.

### Cursor

`.cursor/mcp.json` in the project root. Open mode for general use:
```json
{
  "mcpServers": {
    "alexandria": {
      "command": "alexandria",
      "args": ["mcp", "serve"]
    }
  }
}
```
Pinned mode when the project has its own workspace:
```json
{
  "mcpServers": {
    "alexandria": {
      "command": "alexandria",
      "args": ["mcp", "serve", "--workspace", "customer-acme"]
    }
  }
}
```

### Codex CLI

```bash
codex mcp add alexandria -- alexandria mcp serve
```

Or edit `~/.codex/config.toml`:
```toml
[[mcp_servers]]
name = "alexandria"
command = "alexandria"
args = ["mcp", "serve"]
```

### Windsurf

`~/.codeium/windsurf/mcp_config.json`:
```json
{
  "mcpServers": {
    "alexandria": {
      "command": "alexandria",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Zed

`settings.json` under `experimental.mcp_servers`, same shape.

### Claude.ai (web) — HTTP transport

Claude.ai's connector panel asks for an HTTP MCP URL. Run the daemon:
```bash
alexandria daemon start
```
Then add `http://localhost:<port>/mcp/<workspace>` in the web connector UI. Daemon must be running for the session to work. For remote use across a LAN, bind explicitly (`alexandria daemon start --bind 0.0.0.0 --token <generated>`) and pass the token via header.

## Bootstrapping — `alexandria mcp install`

One-shot installers for the common clients:

```bash
alexandria mcp install claude-code                              # open mode, user-level
alexandria mcp install claude-code --workspace customer-acme    # pinned, writes a project .mcp.json in cwd
alexandria mcp install claude-desktop
alexandria mcp install cursor
alexandria mcp install codex
alexandria mcp install windsurf
```

Each subcommand finds the client's config file at its canonical location, inserts the right block, and prints what it did. Idempotent — re-running updates the entry in place. With no `--workspace` flag it installs open mode; with `--workspace <slug>` it installs pinned mode.

## Auth and trust model

### stdio
No auth. The subprocess inherits OS-user permissions. The trust boundary is "processes running as this user." This matches how every other local MCP server works (git, filesystem, shell-access servers).

### HTTP
Three progressive levels:

1. **Loopback only** — default. `127.0.0.1` bind. No token. Any local process can connect. Matches stdio's trust model.
2. **Loopback + token** — optional. Generate with `alexandria daemon auth token`. Clients pass `Authorization: Bearer <token>`. Protects against accidentally-running-as-root or a hostile local user scenario.
3. **Non-loopback + token** — requires both `--bind` and `--token`. Daemon refuses to start on a public interface without a token.

Tokens are 32-byte random strings stored in `~/.alexandria/secrets/daemon.token.enc`. Revoke with `alexandria daemon auth revoke`.

## Health and observability

- `alexandria mcp status` — lists the running stdio sessions (by parent PID) and the daemon status.
- Each tool call is logged to `~/.alexandria/logs/mcp-<date>.jsonl` with `{ts, workspace, tool, args_hash, latency_ms, result}`. Logs are local-only, rotated weekly.
- The daemon exposes `GET /health` (unauthenticated) and `GET /mcp/<workspace>/health` (authenticated if tokens on).

## What the MCP server does NOT expose

- No CLI passthrough. The agent cannot run arbitrary `alexandria` commands.
- No source/subscription/workspace configuration. Those are user-controlled via the CLI or web UI.
- No shell, no code interpreter, no HTTP fetch. The tool surface is read/search/write markdown only.
- In pinned mode: no access to any workspace except the pinned one.
- In open mode: no access to paths outside `~/.alexandria/workspaces/<any-valid-slug>/`. `config.toml`, `secrets/`, `.trash/`, `templates/`, and `state.db` are not reachable.
- Never exposes raw credentials, even if the agent asks `sources` for adapter details.

## Packaging check — what ships in `pip install alexandria`

After `pip install alexandria`, the following must work out of the box:

1. `alexandria --version`
2. `alexandria init`
3. `alexandria mcp serve` — runs on stdio, speaks MCP protocol v1, exposes every workspace.
4. `alexandria mcp serve --workspace global` — same, pinned to the `global` workspace.
5. `alexandria mcp install claude-code` — writes the client config.
6. The binary is discoverable on `$PATH` (we ship an entry point in `pyproject.toml`).

The MCP server is not an optional extra. It's the primary interaction surface for the guardian agent and must be present in every install.
