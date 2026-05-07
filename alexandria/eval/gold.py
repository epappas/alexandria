"""Gold-query management for the retroactive query benchmark (M6).

A gold query is a question the user has authored together with its
expected answer-topic set and expected citation set. The benchmark
replays each gold query through the agent loop and scores the result
against these expectations — see ``retroactive.py`` for the runner.

The schema reuses ``eval_gold_queries`` from migration ``0008_eval.sql``.
The ``expected`` column holds the JSON shape ``{"answer_topics": [...],
"citations": [...]}``. The ``metric`` column tags the entry with the
metric that consumes it (``"M6"`` for retroactive queries).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

GOLD_METRIC = "M6"


@dataclass(frozen=True)
class GoldQuery:
    """One retroactive-query gold standard entry."""

    query_id: str
    workspace: str
    query: str
    expected_topics: list[str]
    expected_citations: list[str]
    created_at: str


def add_gold(
    conn: sqlite3.Connection,
    workspace: str,
    query: str,
    expected_topics: list[str],
    expected_citations: list[str],
) -> str:
    """Insert a gold query and return its assigned ``query_id``."""
    query_text = query.strip()
    if not query_text:
        raise ValueError("query must be non-empty")
    if not expected_topics and not expected_citations:
        raise ValueError("at least one of expected_topics or expected_citations is required")

    query_id = f"gold-{uuid.uuid4().hex[:12]}"
    expected = json.dumps({
        "answer_topics": [t.strip() for t in expected_topics if t.strip()],
        "citations": [c.strip() for c in expected_citations if c.strip()],
    })
    now = datetime.now(UTC).isoformat()

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO eval_gold_queries "
            "(query_id, workspace, query, expected, metric, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (query_id, workspace, query_text, expected, GOLD_METRIC, now),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return query_id


def list_gold(conn: sqlite3.Connection, workspace: str) -> list[GoldQuery]:
    """Return all gold queries registered for a workspace."""
    rows = conn.execute(
        "SELECT query_id, workspace, query, expected, created_at "
        "FROM eval_gold_queries WHERE workspace = ? AND metric = ? "
        "ORDER BY created_at ASC",
        (workspace, GOLD_METRIC),
    ).fetchall()
    return [_row_to_gold(r) for r in rows]


def get_gold(conn: sqlite3.Connection, query_id: str) -> GoldQuery | None:
    """Look up one gold query by id."""
    row = conn.execute(
        "SELECT query_id, workspace, query, expected, created_at "
        "FROM eval_gold_queries WHERE query_id = ? AND metric = ?",
        (query_id, GOLD_METRIC),
    ).fetchone()
    return _row_to_gold(row) if row else None


def remove_gold(conn: sqlite3.Connection, query_id: str) -> bool:
    """Delete a gold query by id; returns True if a row was removed."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "DELETE FROM eval_gold_queries WHERE query_id = ? AND metric = ?",
            (query_id, GOLD_METRIC),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return cursor.rowcount > 0


def _row_to_gold(row: sqlite3.Row) -> GoldQuery:
    expected = json.loads(row["expected"]) if row["expected"] else {}
    return GoldQuery(
        query_id=row["query_id"],
        workspace=row["workspace"],
        query=row["query"],
        expected_topics=list(expected.get("answer_topics", [])),
        expected_citations=list(expected.get("citations", [])),
        created_at=row["created_at"],
    )
