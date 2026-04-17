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
# Initialize
alxia init
alxia status

# Create a project workspace
alxia project create my-research --description "ML papers"
alxia workspace use my-research

# Ingest from anywhere
alxia ingest ~/Documents/paper.pdf
alxia ingest https://arxiv.org/pdf/2401.12345.pdf
alxia ingest https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)

# Query your knowledge
alxia query "attention mechanisms"

# Connect to Claude Code
alxia mcp install claude-code
```

## Sources

Alexandria ingests from 14 source types:

| Source | Command |
|--------|---------|
| **Local file** | `alxia ingest ~/file.md` |
| **PDF** | `alxia ingest ~/paper.pdf` |
| **URL** (HTML) | `alxia ingest https://example.com/article` |
| **URL** (PDF) | `alxia ingest https://arxiv.org/pdf/2401.12345.pdf` |
| **Git repo** | `alxia source add git-local --name repo --repo-url ~/project` |
| **GitHub** | `alxia source add github --name repo --owner x --repo y` |
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
# Register with Claude Code (stdio transport)
alxia mcp install claude-code

# Or run the HTTP server for other clients
alxia mcp serve-http --port 7219
```

Available MCP tools: `guide`, `overview`, `list`, `grep`, `search`, `read`, `follow`, `history`, `why`, `events`, `timeline`, `git_log`, `git_show`, `git_blame`, `sources`, `subscriptions`.

## CLI Reference

```
alxia init                    Initialize ~/.alexandria/
alxia status                  Operational dashboard
alxia doctor                  Health checks

alxia ingest <file-or-url>    Ingest a source (file, PDF, URL)
alxia query <question>        Search across all knowledge
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
alxia hooks install <client>  Install capture hooks
alxia capture conversation    Capture an agent session

alxia eval run                Run quality metrics (M1-M5)
alxia daemon start            Start background scheduler
alxia logs show               View structured logs
```

## Architecture

- **SQLite + filesystem hybrid**: filesystem is source of truth for documents, SQLite for search/metadata/events
- **FTS5** for keyword search (no vectors, no RAG — the agent IS the retriever)
- **Hostile verifier**: every wiki write is verified before commit (citations, quote anchors, cascade policy)
- **Belief revision**: structured claims with supersession chains and provenance
- **AES-256-GCM vault**: encrypted secrets with PBKDF2 key derivation
- **Structured JSONL logging** with run_id correlation
- **8 schema migrations** applied automatically on init

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
uv run pytest tests/       # 352 tests
./scripts/build.sh          # test + build
./scripts/publish.sh        # test + build + PyPI + git tag
```

## License

MIT
