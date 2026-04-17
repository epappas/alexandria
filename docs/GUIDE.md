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

### 3. Create a workspace for your project

```bash
alxia project create ml-research --description "Machine learning papers and notes"
alxia workspace use ml-research
```

Workspaces isolate knowledge by project. The `global` workspace is for general knowledge. Each project workspace has its own `raw/`, `wiki/`, and source configurations.

## Ingesting Knowledge

### From files

```bash
# Markdown, text
alxia ingest ~/notes/transformer-notes.md

# PDF (arxiv papers, books, slides)
alxia ingest ~/Downloads/attention-is-all-you-need.pdf
```

### From URLs

```bash
# Web pages
alxia ingest https://lilianweng.github.io/posts/2023-06-23-agent/

# PDF URLs (arxiv, conference proceedings)
alxia ingest https://arxiv.org/pdf/2401.12345.pdf

# Wikipedia
alxia ingest https://en.wikipedia.org/wiki/Retrieval-augmented_generation

# GitHub gists
alxia ingest https://gist.githubusercontent.com/user/id/raw/file.md
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

This is where Alexandria really shines. Connect it to Claude Code:

```bash
alxia mcp install claude-code
```

Restart Claude Code. Now Claude can access your knowledge through MCP tools:

- **"What do my notes say about transformers?"** — Claude calls `search` and `read`
- **"Summarize the recent posts from my RSS feeds"** — Claude calls `subscriptions` and `read`
- **"What changed in my-project this week?"** — Claude calls `events` and `git_log`
- **"Why do I believe X?"** — Claude calls `why` to trace belief provenance

The MCP server exposes 16 tools: `guide`, `overview`, `list`, `grep`, `search`, `read`, `follow`, `history`, `why`, `events`, `timeline`, `git_log`, `git_show`, `git_blame`, `sources`, `subscriptions`.

### Pinned vs Open mode

By default, the MCP server runs in **open mode** — all workspaces are accessible. For project-specific use:

```bash
# Pin to one workspace
alxia mcp serve --workspace ml-research
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

Alexandria can capture your AI coding sessions:

```bash
# Install hooks for Claude Code
alxia hooks install claude-code

# Or for Codex
alxia hooks install codex

# Manually capture a transcript
alxia capture conversation ~/path/to/session.jsonl --client claude-code

# List captures
alxia captures
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

1. **Morning**: `alxia sync` pulls overnight RSS, GitHub activity, git commits
2. **During work**: `alxia ingest` papers, articles, notes as you find them
3. **In Claude Code**: ask questions, Claude searches your Alexandria knowledge
4. **Weekly**: `alxia synthesize` generates a digest of what happened
5. **Maintenance**: `alxia lint` checks wiki health, `alxia eval run` tracks quality
