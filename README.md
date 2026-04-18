# Alexandria

Local-first single-user knowledge engine. Accumulates your gathered knowledge (raw sources, compiled wiki pages, event streams, AI conversations) and exposes it via MCP to connected agents like Claude Code for retroactive query, retrieval, and synthesis.

Alexandria is **not** a chat client. Interactive conversations happen in your existing MCP-capable agent (Claude Code, Cursor, Codex). Alexandria is the knowledge engine those agents connect to.

## Install

```bash
pip install alexandria-wiki          # core
pip install "alexandria-wiki[pdf]"   # + PDF support
pip install "alexandria-wiki[all]"   # + PDF + YouTube transcripts
```

Or with uv:

```bash
uvx alexandria-wiki
# or
uv tool install alexandria-wiki
```

## Quick Start

```bash
# 1. Initialize
alxia init

# 2. Connect to Claude Code (one-time setup)
alxia mcp install claude-code         # register MCP server
alxia hooks install claude-code       # auto-capture conversations

# 3. Restart Claude Code — Alexandria tools are now available

# 4. Ingest from anywhere
alxia ingest ~/Documents/paper.pdf
alxia ingest https://arxiv.org/abs/2407.09450
alxia ingest ./my-project                         # whole directory
alxia ingest epappas/alexandria                    # GitHub repo
alxia ingest ~/.claude/projects/*/session.jsonl    # conversation

# 5. Query your knowledge
alxia query "What do you know?"
```

## Sources

Alexandria ingests from 14 source types:

| Source | Command |
|--------|---------|
| **Local file** | `alxia ingest ~/file.md` |
| **PDF** | `alxia ingest ~/paper.pdf` |
| **URL** (HTML) | `alxia ingest https://example.com/article` |
| **Code** (.py/.ts/.rs/.go/.tf/.yml) | `alxia ingest main.py` (AST extraction) |
| **Directory** | `alxia ingest ./my-project` |
| **Git repo** | `alxia ingest https://github.com/owner/repo` |
| **GitHub shorthand** | `alxia ingest owner/repo` |
| **Conversation** | `alxia ingest ~/.claude/projects/*/session.jsonl` |
| **GitHub** (events) | `alxia source add github --name repo --owner x --repo y` |
| **RSS/Atom** | `alxia source add rss --name blog --feed-url https://example.com/feed` |
| **YouTube** | `alxia source add youtube --name talks --urls "https://youtu.be/abc"` |
| **Notion** | `alxia source add notion --name wiki --token-ref key --page-ids "abc"` |
| **HuggingFace** | `alxia source add huggingface --name models --repos "meta-llama/Llama-3-8b"` |
| **Obsidian/Folder** | `alxia source add folder --name vault --path ~/ObsidianVault` |
| **Zip/Tar** | `alxia source add archive --name papers --path ~/papers.zip` |
| **IMAP** | `alxia source add imap --name mail --imap-host imap.gmail.com --imap-user me` |
| **Clipboard** | `alxia paste --title "note" --content "quick thought"` |

After adding sources, pull everything with:

```bash
alxia sync
```

## MCP Integration

Alexandria exposes your knowledge to AI agents via the [Model Context Protocol](https://modelcontextprotocol.io/).

```bash
# Register with Claude Code (one-time)
alxia mcp install claude-code

# Install conversation capture hooks (one-time)
alxia hooks install claude-code

# Restart Claude Code — done. Verify:
alxia mcp status
alxia hooks verify claude-code
```

After setup, Claude Code has 20 Alexandria tools:

| Category | Tools |
|----------|-------|
| Navigate | `guide`, `overview`, `list`, `search`, `grep`, `read`, `follow` |
| History | `history`, `why`, `timeline`, `events` |
| Git | `git_log`, `git_show`, `git_blame` |
| Sources | `sources`, `subscriptions` |
| Write | `ingest`, `query`, `belief_add`, `belief_supersede` |

For other MCP clients:
```bash
alxia mcp serve-http --port 7219
```

## CLI Reference

```
alxia init                    Initialize ~/.alexandria/
alxia status                  Operational dashboard
alxia doctor                  Health checks

alxia ingest <source>         Ingest file, dir, URL, repo, or conversation
alxia query <question>        LLM-powered answers from your knowledge base
alxia why <topic>             Belief explainability + provenance
alxia lint                    Find wiki rot (stale citations)
alxia synthesize              Generate temporal digest

alxia source add <type>       Add a source adapter
alxia source list             List configured sources
alxia sync                    Pull from all sources
alxia subscriptions poll      Poll RSS + IMAP
alxia subscriptions list      Show pending items

alxia workspace use <slug>    Switch workspace
alxia project create <name>   Create a project workspace

alxia secrets set <ref>       Store an encrypted secret
alxia beliefs cleanup         Dedup beliefs and remove orphans
alxia hooks install <client>  Install capture hooks
alxia capture conversation    Capture an agent session

alxia eval run                Run quality metrics (M1-M5)
alxia daemon start            Start background scheduler
alxia logs show               View structured logs
```

## Architecture

- **SQLite + filesystem hybrid**: filesystem is source of truth for documents, SQLite for search/metadata/events
- **Hybrid search**: FTS5 BM25 + recency decay + belief support scoring (no vectors, no RAG — the agent IS the retriever)
- **AST extraction**: Python, TypeScript, Rust, Go, Terraform, Ansible, YAML parsed into structured beliefs
- **Hostile verifier**: every wiki write is verified before commit (citations, quote anchors, cascade policy)
- **Belief revision**: structured claims with supersession chains and provenance
- **Conversation capture**: auto-captures Claude Code sessions with artifact extraction (papers, repos)
- **Self-awareness**: Alexandria can answer questions about its own state and capabilities
- **Document dedup**: content-hash check skips re-ingest of unchanged files
- **Belief integrity**: supersede-all-then-restore prevents duplicates; `alxia beliefs cleanup` removes orphans
- **AES-256-GCM vault**: encrypted secrets with PBKDF2 key derivation
- **Structured JSONL logging** with run_id correlation
- **10 schema migrations** applied automatically on init

See `docs/architecture/` for the 20 architecture documents.

## Docker

```bash
docker build -t alexandria .
docker run -v ~/.alexandria:/data alexandria init
docker run -v ~/.alexandria:/data alxia status
```

## Development

```bash
git clone git@github.com:epappas/alexandria.git
cd alexandria
uv sync --dev
uv run pytest tests/       # 352+ tests
./scripts/build.sh          # test + build
./scripts/publish.sh        # test + build + PyPI + git tag
```

## License

MIT
