# 03 — Workspaces and Scopes

> **Replaces the earlier multi-tenant doc.** `llmwiki` is single-user. The only boundary that matters is the workspace — a self-contained body of knowledge.

## Two kinds of workspace

### Global workspace
`~/.llmwiki/workspaces/global/`

- Exactly one. Created at `llmwiki init`.
- Holds the user's **general knowledge** — personal learning, long-standing interests, cross-cutting notes.
- Default target when no workspace is specified.

### Project workspaces
`~/.llmwiki/workspaces/<slug>/`

- Many. Created with `llmwiki project create <name>`.
- One per customer, client, research topic, product, or coherent body of work.
- Each has its own sources, subscriptions, log, and wiki pages.
- Self-contained: deleting the directory removes the workspace (and the SQLite index rows reference by path, so they clean up on next `llmwiki reindex`).

Example layouts:

```
~/.llmwiki/workspaces/
├── global/              # my general knowledge
├── customer-acme/       # work I'm doing for Acme Corp
├── paper-transformers/  # a literature review
├── side-project-xyz/    # personal build project
└── learning-rust/       # a topic I'm studying
```

## What a workspace contains

```
workspaces/<slug>/
├── SKILL.md              # the agent contract for this workspace (extends the global template)
├── config.toml           # name, description, contract version, per-workspace settings
├── raw/                  # immutable source material organized by adapter
│   ├── notion/
│   ├── github/
│   ├── papers/
│   ├── local/
│   └── subscriptions/
│       ├── newsletter/
│       └── twitter/
└── wiki/                 # compiled markdown pages, agent-owned
    ├── overview.md       # mandatory hub page
    ├── index.md          # mandatory table of contents
    ├── log.md            # mandatory append-only operation log
    ├── concepts/
    │   └── ...md
    ├── entities/
    │   └── ...md
    └── archives/         # immutable query snapshots
```

Nothing else. If a user wants something else, they put it in `raw/` and let the agent compile it.

## One workspace at a time

The guardian agent is **always scoped to one workspace** for the duration of a session. It is passed as an argument (`--workspace customer-acme`) or selected via `llmwiki workspace use customer-acme` which sets the current default.

The agent's MCP tools all operate inside that workspace's directory. A tool cannot reach outside it. There is no `search --workspace=other`, no `read("../other/...")`, no cross-workspace writes. This is enforced in the tool layer by resolving every path against the workspace root and rejecting paths that escape it.

Rationale: workspaces represent distinct knowledge scopes. Mixing them in the agent's context is exactly what corrupts the wiki. Steph Ango's vault-separation rule applies **between workspaces** as much as between us and Obsidian.

## Switching workspaces

Three ways:

1. **Explicit argument** on every command: `llmwiki query --workspace customer-acme "..."`.
2. **Current workspace** set in `~/.llmwiki/config.toml` under `[state] current_workspace = "customer-acme"`. Commands without `--workspace` use this. The CLI exposes `llmwiki workspace use <slug>` and `llmwiki workspace current`.
3. **Environment variable** `LLMWIKI_WORKSPACE` for scripts and agent sessions.

The daemon serves a separate MCP endpoint per workspace (e.g. `http://localhost:<port>/mcp/customer-acme`) so Claude/Cursor connectors can be pinned per project. Switching is a connector change, not a runtime state flip — avoids silent context bleed.

## Cross-workspace queries — deferred

The user will eventually want "what do I know about OAuth across all my projects?" That's a cross-workspace query. It is explicitly **not** supported at MVP because:

1. The agent's system prompt becomes ambiguous (which schema? which log?).
2. Citations need to carry workspace identifiers, changing the file-reference format.
3. Write-back (archive the answer) has no obvious target.

Future: a dedicated `llmwiki query --global` or a `meta` workspace that indexes summaries from every other workspace. See `07_open_questions.md`.

## Config surface

`~/.llmwiki/config.toml`:

```toml
[general]
data_dir = "~/.llmwiki"
default_llm = "claude-opus-4-6"
editor = "nvim"

[state]
current_workspace = "global"

[daemon]
enabled = false
port = 7219
web_ui = true
mcp = true

[limits]
max_pages_per_workspace = 2000
max_tokens_per_ingest = 200000

[secrets]
keyring_service = "llmwiki"
```

`~/.llmwiki/workspaces/<slug>/config.toml`:

```toml
[workspace]
name = "Acme Corp"
description = "Everything I'm doing for Acme"
contract_version = "v1"
created_at = "2026-04-15"

[agent]
topics = ["integration", "contracts", "infra", "meetings"]
# optional: constrains the agent's topic subdirectories
```

## Creating and destroying workspaces

```bash
llmwiki project create customer-acme --description "Acme Corp work"
llmwiki project list
llmwiki project delete customer-acme     # prompts for confirmation, archives to trash
llmwiki project rename customer-acme acme
llmwiki project info customer-acme        # sources, pages, last activity
```

Delete is soft: the directory moves to `~/.llmwiki/.trash/<timestamp>/`. `llmwiki gc` empties trash older than N days. SQLite rows are purged on next `reindex`.

## Workspace templates

When creating a project, the user can pick a template that seeds topic directories and a tailored SKILL.md:

- `--template customer` — topics: `overview`, `contracts`, `meetings`, `integrations`, `decisions`.
- `--template research` — topics: `papers`, `concepts`, `methods`, `open-questions`.
- `--template product` — topics: `features`, `bugs`, `decisions`, `user-feedback`.
- `--template learning` — topics: `notes`, `examples`, `exercises`, `references`.
- `--template minimal` — just `overview.md`, `index.md`, `log.md`, no topics.

Templates live in the package at `llmwiki/templates/workspaces/`. Users can override with `~/.llmwiki/templates/`.
