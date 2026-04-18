# Alexandria User Guide

## What is Alexandria?

Alexandria is a personal knowledge engine. It collects information from your sources — papers, repos, blogs, notes, conversations — stores it locally, and makes it searchable by you and your AI coding agents via MCP.

Think of it as: **your second brain, queryable by AI.**

## Getting Started

### 1. Install

```bash
pip install "alexandria-wiki[all]"
```

This installs the core engine plus PDF and YouTube support. If you only want the basics:

```bash
pip install alexandria-wiki
```

### 2. Initialize

```bash
alxia init
```

This creates `~/.alexandria/` with:
- A SQLite database (`state.db`)
- A `global` workspace with `raw/` and `wiki/` directories
- A config file (`config.toml`)

Check it worked:

```bash
alxia status
alxia doctor
```

### 3. Connect to Claude Code

```bash
# Register Alexandria as an MCP server (one-time)
alxia mcp install claude-code

# Install hooks to auto-capture conversations (one-time)
alxia hooks install claude-code
```

Restart Claude Code. You now have 20 Alexandria tools available (`mcp__alexandria__search`, `mcp__alexandria__ingest`, `mcp__alexandria__query`, etc.).

To verify:
```bash
alxia mcp status
alxia hooks verify claude-code
```

### 4. Create a workspace for your project

```bash
alxia project create ml-research --description "Machine learning papers and notes"
alxia workspace use ml-research
```

Workspaces isolate knowledge by project. The `global` workspace is for general knowledge. Each project workspace has its own `raw/`, `wiki/`, and source configurations.

## Ingesting Knowledge

The `ingest` command handles everything: files, directories, URLs, git repos, and conversations.

### From files

```bash
# Markdown, text
alxia ingest ~/notes/transformer-notes.md

# PDF (arxiv papers, books, slides)
alxia ingest ~/Downloads/attention-is-all-you-need.pdf

# Code files (Python, TypeScript, Rust, Go, Terraform, Ansible, YAML)
# AST extraction produces structured beliefs automatically
alxia ingest ~/project/main.py --topic myproject
```

### From URLs

```bash
# Web pages
alxia ingest https://lilianweng.github.io/posts/2023-06-23-agent/

# Arxiv papers
alxia ingest https://arxiv.org/abs/2407.09450

# Wikipedia
alxia ingest https://en.wikipedia.org/wiki/Retrieval-augmented_generation
```

### From directories and git repos

```bash
# Local directory (walks tree, ingests all supported files)
alxia ingest ./my-project --topic myproject

# Git repo URL (shallow clones, then ingests)
alxia ingest https://github.com/owner/repo.git

# GitHub shorthand
alxia ingest owner/repo
```

### From conversations

```bash
# Ingest a Claude Code session transcript
# Captures the conversation AND ingests all referenced artifacts (papers, repos)
alxia ingest ~/.claude/projects/*/session-id.jsonl --topic research

# Ingest all sessions from a project directory
alxia ingest ~/.claude/projects/-home-me-myproject/ --topic research
```

### From continuous sources

These are sources that update over time. Add them once, then `alxia sync` pulls new content.

```bash
# RSS/Atom feeds (blogs, substacks)
alxia source add rss --name simon-willison --feed-url "https://simonwillison.net/atom/everything/"
alxia source add rss --name ai-news --feed-url "https://buttondown.com/ainews/rss"

# Git repositories (tracks commits as events)
alxia source add git-local --name my-project --repo-url ~/workspace/my-project

# GitHub issues, PRs, releases
alxia source add github --name my-repo --owner myorg --repo myrepo --token-ref github-pat

# YouTube transcripts
alxia source add youtube --name lectures --urls "https://youtu.be/video1,https://youtu.be/video2"

# HuggingFace model cards
alxia source add huggingface --name models --repos "meta-llama/Llama-3-8b,mistralai/Mistral-7B"

# Obsidian vault or any folder (auto-discovers file types)
alxia source add folder --name obsidian --path ~/Documents/ObsidianVault

# Zip/tar archives
alxia source add archive --name papers --path ~/Downloads/conference-papers.zip

# Notion pages
alxia source add notion --name team-wiki --token-ref notion-key --page-ids "abc-123,def-456"

# Email newsletters
alxia source add imap --name newsletters --imap-host imap.gmail.com --imap-user me@gmail.com --imap-pass-ref gmail-app-password --from-allowlist "*@substack.com"

# Pull everything
alxia sync

# Check what came in
alxia subscriptions list
```

### Quick capture

For quick notes and thoughts:

```bash
alxia paste --title "meeting notes" --content "Decided to use SQLite instead of Postgres for simplicity"
```

## Querying Your Knowledge

### From the CLI

```bash
# Search across everything (documents, beliefs, events, subscriptions)
alxia query "attention mechanisms"

# Ask why something is believed (traces provenance to sources)
alxia why "transformer"

# JSON output for scripting
alxia query "RAG vs fine-tuning" --json
```

### From Claude Code (via MCP)

This is where Alexandria really shines. If you followed step 3 above, Claude Code already has access. Examples of what to ask:

- **"What do my notes say about transformers?"** — Claude calls `search` and `read`
- **"Ingest this paper: https://arxiv.org/abs/2407.09450"** — Claude calls `ingest`
- **"Ingest my project at ./backend"** — Claude calls `ingest` on the directory
- **"What changed in my-project this week?"** — Claude calls `events` and `git_log`
- **"Why do I believe X?"** — Claude calls `why` to trace belief provenance
- **"What do you know?"** — Claude calls `query`, Alexandria answers with self-knowledge
- **"Add a belief: Transformers use self-attention"** — Claude calls `belief_add`

The MCP server exposes 20 tools:

| Category | Tools |
|----------|-------|
| Navigate | `guide`, `overview`, `list`, `search`, `grep`, `read`, `follow` |
| History | `history`, `why`, `timeline`, `events` |
| Git | `git_log`, `git_show`, `git_blame` |
| Sources | `sources`, `subscriptions` |
| Write | `ingest`, `query`, `belief_add`, `belief_supersede` |

### Pinned vs Open mode

By default, the MCP server runs in **open mode** — all workspaces are accessible. For project-specific use:

```bash
# Pin to one workspace in the project's .mcp.json
alxia mcp install claude-code --workspace ml-research
```

## Managing Secrets

For sources that need authentication (GitHub tokens, Notion keys, IMAP passwords):

```bash
# Store a secret (prompted for value)
alxia secrets set github-pat

# Use it in a source via --token-ref
alxia source add github --name repo --owner org --repo name --token-ref github-pat

# List stored secrets (never shows values)
alxia secrets list

# Rotate a secret
alxia secrets rotate github-pat
```

Secrets are encrypted with AES-256-GCM. The vault passphrase comes from the `ALEXANDRIA_VAULT_PASSPHRASE` environment variable or your OS keyring.

## Wiki Health

```bash
# Check for stale citations, missing sources, orphaned beliefs
alxia lint

# Run quality metrics
alxia eval run

# Generate a weekly digest from recent activity
alxia synthesize --dry-run    # preview
alxia synthesize              # generate
```

## Background Daemon

For continuous syncing without manual `alxia sync`:

```bash
# Start (foreground, for testing)
alxia daemon start --foreground

# Start (background)
alxia daemon start

# Check status
alxia daemon status

# Stop
alxia daemon stop
```

The daemon runs source syncs every 5 minutes and subscription polls every hour.

## Capturing Conversations

Alexandria auto-captures your AI coding sessions when hooks are installed:

```bash
# Install hooks (one-time, already done if you followed Getting Started)
alxia hooks install claude-code

# Verify hooks are active
alxia hooks verify claude-code
```

When a Claude Code session ends, the Stop hook fires and:
1. Parses the JSONL transcript
2. Converts to a searchable wiki page
3. Extracts referenced artifacts (papers, repos, URLs)
4. Ingests each artifact through the full pipeline

You can also manually ingest conversations:

```bash
# Ingest a specific session
alxia ingest ~/.claude/projects/*/session-id.jsonl --topic research

# Ingest all sessions from a project
alxia ingest ~/.claude/projects/-home-me-myproject/ --topic research

# Or use the capture command directly
alxia capture conversation ~/path/to/session.jsonl --client claude-code
alxia captures    # list captured sessions
```

## Workspaces

```bash
alxia project create paper-review --description "Reviewing ICML submissions"
alxia workspace use paper-review
alxia workspace list
alxia workspace current

# Switch back
alxia workspace use global
```

Each workspace is isolated: separate `raw/`, `wiki/`, sources, beliefs, and events.

## Docker

```bash
docker run -v ~/.alexandria:/data ghcr.io/epappas/alexandria init
docker run -v ~/.alexandria:/data ghcr.io/epappas/alexandria status
docker run -v ~/.alexandria:/data ghcr.io/epappas/alexandria ingest https://arxiv.org/pdf/2401.12345.pdf
```

## Typical Workflow

1. **Setup (once)**: `alxia init && alxia mcp install claude-code && alxia hooks install claude-code`
2. **Morning**: `alxia sync` pulls overnight RSS, GitHub activity, git commits
3. **During work**: `alxia ingest` papers, repos, articles, notes as you find them
4. **In Claude Code**: ask questions — Claude searches your Alexandria knowledge via MCP tools
5. **After sessions**: conversations auto-captured by hooks, referenced papers/repos ingested
6. **Weekly**: `alxia synthesize` generates a digest of what happened
7. **Querying**: `alxia query "What do I know about X?"` for grounded answers from your knowledge base
8. **Maintenance**: `alxia lint` checks wiki health, `alxia eval run` tracks quality

## LLM Configuration

Alexandria uses an LLM for query answering, content summarization, and belief extraction during ingest. It auto-detects providers in this order:

1. **Claude Max/Pro subscription** (via Claude Code SDK) — no API key needed, works automatically if `claude` CLI is installed
2. **ANTHROPIC_API_KEY** — direct Anthropic API
3. **OPENAI_API_KEY** — OpenAI / GPT models
4. **OPENROUTER_API_KEY** — OpenRouter (any model)
5. **GOOGLE_API_KEY** — Google Gemini
6. **config.toml `[llm]` section** — local models (Ollama, vLLM, SGLang)

Without an LLM, Alexandria still works for ingest (mechanical extraction), search (FTS5), and code analysis (AST). Query and belief extraction require an LLM.
