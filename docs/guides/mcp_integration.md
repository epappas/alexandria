# MCP integration — best practices and caveats

How to register alexandria's MCP server with your coding agent (Claude
Code, Cursor, Codex) so it's available in every session, and the
operational gotchas that come with it.

## Quick decision: scope and workspace

Two orthogonal decisions:

1. **Claude Code scope** — which sessions see alexandria.
   - `local`: this project directory only.
   - `project`: shared with teammates via `<repo>/.mcp.json`.
   - `user`: every `claude` session you run, in every directory. **Default
     recommendation for personal use.**
2. **Alexandria workspace** — which knowledge bucket the server writes to.
   - Pinned (`--workspace <slug>`): one workspace, no per-call argument
     needed. **Default recommendation.**
   - Open (no `--workspace`): every tool call requires an explicit
     `workspace` argument. Only useful if you actively want multi-bucket
     access from one server.

## Minimum viable setup (user scope, pinned to `global`)

```bash
claude mcp remove alexandria -s local   2>/dev/null
claude mcp remove alexandria -s project 2>/dev/null
claude mcp remove alexandria -s user    2>/dev/null

claude mcp add -s user alexandria -- \
  "$(which alexandria)" mcp serve --workspace global
```

Every future Claude Code session inherits this automatically. Exit and
relaunch any active session to pick it up — MCP config is read at
startup, not re-polled.

## Per-project override

When a project has enough distinct knowledge to warrant its own
workspace:

```bash
alxia project create writeups
cd ~/path/to/writeups
alxia mcp install claude-code --workspace writeups
```

The project-scope `.mcp.json` shadows the user default in that
directory. Commit it only if teammates should share the pin; otherwise
`.gitignore` it.

## Speed: pin a faster model

The MCP server spawns `claude -p` subprocesses for LLM calls during
ingest. Default model is whatever your Claude Code config uses (usually
Sonnet). To pin Haiku (3–5× faster on ingest workload) for the MCP
server specifically, without affecting your interactive Claude Code
sessions:

```bash
claude mcp remove alexandria -s user 2>/dev/null
claude mcp add -s user alexandria \
  -e ALEXANDRIA_CLAUDE_MODEL=haiku \
  -- "$(which alexandria)" mcp serve --workspace global
```

**Note the syntax.** The server name (`alexandria`) must come **before**
`-e` because `claude`'s `-e` flag is variadic and will otherwise consume
the name as a second env var. Always terminate the env list with `--`
before the command.

## Caveats

### Registration is read at session start

MCP config changes don't propagate into running sessions. After any
`claude mcp add` / `remove`, exit and relaunch `claude` for the
affected directory. `/mcp` inside a session shows what's currently
loaded.

### The MCP server runs as a subprocess of `claude`

It inherits the parent's environment but loses `CLAUDECODE=1` (which
alexandria's LLM provider detection sets to avoid nested
rate-limit conflicts). This is correct behavior — without clearing
`CLAUDECODE`, the Claude Code SDK provider would refuse to run,
falling back to the mechanical non-LLM ingest path and producing
lower-quality wiki pages.

### Open mode is strictly more work than pinned mode

In open mode (`alxia mcp serve` without `--workspace`), every tool
call requires `workspace="..."`. Agents forget; knowledge lands in
the wrong bucket; cleanup is manual. Pin unless you have a concrete
reason not to.

### The env-var model override only affects the Claude Code SDK path

`ALEXANDRIA_CLAUDE_MODEL` is consumed by the subprocess provider that
calls `claude -p`. If you've configured an explicit API provider in
`~/.alexandria/config.toml` under `[llm]`, that takes priority and
the env var is ignored. Set `[llm].model` in config.toml if you're on
the direct Anthropic or OpenAI path.

### Ingests are slow but not stalled

A single URL or file ingest runs through:

1. Fetch / copy to `raw/`.
2. LLM call for title + summary + belief extraction.
3. Deterministic verifier (footnote + quote-anchor checks).
4. Cascade decision (new_page / merge / hedge).
5. FTS indexing.

Total: ~30–90 seconds per source. A batch of N URLs takes roughly N
minutes. Check `alxia runs list` or the journal log rather than
assuming stall.

### Rate limits on Claude Max / Pro subscriptions

If the ingest path errors with "Rate limited by Claude Max
subscription", close any other interactive Claude Code sessions or
set `ANTHROPIC_API_KEY` for independent API access (bypasses the
subscription rate limit).

### Tools appear as `mcp__alexandria__<name>`

The naming is automatic — `claude` prefixes server tool names with
`mcp__<server-name>__`. If you see a tool in an agent log and wonder
where it came from, the prefix identifies the MCP server.

## Verification

```bash
claude mcp list                    # alexandria should appear
# then in a fresh session:
# /mcp                             — lists connected servers
```

Inside a session, ask the agent to use `overview` or `search` against
alexandria and confirm the call succeeds.
