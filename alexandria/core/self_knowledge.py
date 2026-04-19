"""Alexandria self-knowledge — introspection and capabilities.

Generates a live snapshot of what Alexandria knows, what it can do,
and what it has ingested. Used by the agent loop when the query is
about Alexandria itself.
"""

from __future__ import annotations

import sqlite3

from alexandria import __version__

CAPABILITIES = """Alexandria is a local-first single-user knowledge engine (v{version}).
It accumulates knowledge from multiple source types and exposes it via MCP
to connected AI agents for query and synthesis.

## What Alexandria can do

- **Ingest** files, directories, URLs, git repos, PDFs, conversations
- **Search** across all knowledge using hybrid scoring (BM25 + recency + belief support)
- **Query** natural language questions with LLM-powered answers grounded in sources
- **Track beliefs** — structured claims with supersession chains and provenance
- **AST extraction** — parse Python, TypeScript, Rust, Go, Terraform, Ansible, YAML code structure
- **Capture conversations** — ingest Claude Code sessions and extract referenced artifacts (papers, repos)

## Source types supported

Files (.md, .txt, .pdf), URLs (HTML pages, arxiv, Wikipedia), git repos (local + GitHub),
Python/TypeScript/Rust/Go code, Terraform/Ansible/YAML configs, RSS feeds, YouTube transcripts,
Notion exports, HuggingFace datasets, IMAP newsletters, Obsidian vaults, archives (.zip, .tar.gz).

## MCP tools provided

search, grep, read, list, guide, overview, follow, why, history, timeline, events,
sources, subscriptions, beliefs, ingest, query, belief_add, belief_supersede.

## Architecture

- Filesystem is source of truth (raw/ + wiki/ layers)
- SQLite + FTS5 for search and metadata
- No vectors, no RAG — the agent IS the retriever
- Every wiki write goes through a deterministic verifier
- Beliefs are structured claims with supersession chains
"""


def gather_self_knowledge(conn: sqlite3.Connection, workspace: str) -> str:
    """Gather a live snapshot of Alexandria's state for self-referential queries."""
    parts = [CAPABILITIES.format(version=__version__)]

    # Statistics
    stats = _gather_stats(conn, workspace)
    parts.append("\n## Current state\n")
    parts.append(f"- Documents: {stats['doc_count']} ({stats['wiki_count']} wiki, {stats['raw_count']} raw)")
    parts.append(f"- Beliefs: {stats['belief_count']} current, {stats['superseded_count']} superseded")
    parts.append(f"- Topics: {', '.join(stats['topics'][:20]) or 'none'}")
    parts.append(f"- Runs: {stats['run_count']} total ({stats['committed_count']} committed)")

    # Recent documents
    if stats["recent_docs"]:
        parts.append("\n## Recently ingested\n")
        for doc in stats["recent_docs"][:10]:
            parts.append(f"- {doc['title']} ({doc['path']}) — {doc['updated']}")

    # Top topics by belief count
    if stats["topic_beliefs"]:
        parts.append("\n## Knowledge density by topic\n")
        for topic, count in stats["topic_beliefs"][:10]:
            parts.append(f"- {topic}: {count} belief(s)")

    return "\n".join(parts)


def _gather_stats(conn: sqlite3.Connection, workspace: str) -> dict:
    """Query database for live statistics."""
    stats: dict = {}

    row = conn.execute(
        "SELECT COUNT(*) as c FROM documents WHERE workspace = ?", (workspace,)
    ).fetchone()
    stats["doc_count"] = row["c"]

    row = conn.execute(
        "SELECT COUNT(*) as c FROM documents WHERE workspace = ? AND layer = 'wiki'", (workspace,)
    ).fetchone()
    stats["wiki_count"] = row["c"]
    stats["raw_count"] = stats["doc_count"] - stats["wiki_count"]

    row = conn.execute(
        "SELECT COUNT(*) as c FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NULL", (workspace,)
    ).fetchone()
    stats["belief_count"] = row["c"]

    row = conn.execute(
        "SELECT COUNT(*) as c FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NOT NULL", (workspace,)
    ).fetchone()
    stats["superseded_count"] = row["c"]

    topics = conn.execute(
        """SELECT DISTINCT topic FROM wiki_beliefs
        WHERE workspace = ? AND superseded_at IS NULL ORDER BY topic""",
        (workspace,),
    ).fetchall()
    stats["topics"] = [r["topic"] for r in topics]

    try:
        row = conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()
        stats["run_count"] = row["c"]
        row = conn.execute("SELECT COUNT(*) as c FROM runs WHERE status = 'committed'").fetchone()
        stats["committed_count"] = row["c"]
    except Exception:
        stats["run_count"] = 0
        stats["committed_count"] = 0

    recent = conn.execute(
        """SELECT title, path, updated_at FROM documents
        WHERE workspace = ? AND layer = 'wiki'
        ORDER BY updated_at DESC LIMIT 10""",
        (workspace,),
    ).fetchall()
    stats["recent_docs"] = [
        {"title": r["title"], "path": r["path"], "updated": r["updated_at"]}
        for r in recent
    ]

    topic_beliefs = conn.execute(
        """SELECT topic, COUNT(*) as cnt FROM wiki_beliefs
        WHERE workspace = ? AND superseded_at IS NULL
        GROUP BY topic ORDER BY cnt DESC""",
        (workspace,),
    ).fetchall()
    stats["topic_beliefs"] = [(r["topic"], r["cnt"]) for r in topic_beliefs]

    return stats
