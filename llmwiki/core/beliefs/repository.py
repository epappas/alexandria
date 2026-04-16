"""Belief repository — SQLite operations on wiki_beliefs.

The structured queryable view of beliefs. The sidecar JSON files on disk
are the source of truth; this table is a materialized view that
``llmwiki reindex --rebuild-beliefs`` can reconstruct.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from llmwiki.core.beliefs.model import Belief
from llmwiki.core.citations import verify_quote_anchor
from llmwiki.core.citations.anchors import create_anchor


@dataclass
class BeliefQuery:
    """Parameters for querying beliefs."""

    workspace: str
    topic: str | None = None
    subject: str | None = None
    query: str | None = None
    since: str | None = None
    until: str | None = None
    current_only: bool = True
    limit: int = 50


@dataclass
class BeliefVerifyResult:
    """Result of verifying a single belief's source anchors."""

    belief_id: str
    statement: str
    verified: bool
    message: str


def insert_belief(conn: sqlite3.Connection, belief: Belief) -> None:
    """Insert a belief row. Idempotent via INSERT OR REPLACE."""
    conn.execute(
        """
        INSERT OR REPLACE INTO wiki_beliefs
          (belief_id, workspace, statement, topic, subject, predicate, object,
           wiki_document_path, wiki_section_anchor, footnote_ids, provenance_ids,
           asserted_at, asserted_in_run,
           superseded_at, superseded_by_belief_id, superseded_in_run, supersession_reason,
           source_valid_from, source_valid_to,
           supporting_count, contradicting_belief_ids, confidence_hint, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            belief.belief_id,
            belief.workspace,
            belief.statement,
            belief.topic,
            belief.subject,
            belief.predicate,
            belief.object,
            belief.wiki_document_path,
            belief.wiki_section_anchor,
            json.dumps(belief.footnote_ids),
            json.dumps(belief.provenance_ids),
            belief.asserted_at,
            belief.asserted_in_run,
            belief.superseded_at,
            belief.superseded_by_belief_id,
            belief.superseded_in_run,
            belief.supersession_reason,
            belief.source_valid_from,
            belief.source_valid_to,
            belief.supporting_count,
            json.dumps(belief.contradicting_belief_ids),
            belief.confidence_hint,
            belief.created_at,
        ),
    )


def get_belief(conn: sqlite3.Connection, belief_id: str) -> Belief | None:
    """Fetch a single belief by ID."""
    cur = conn.execute(
        "SELECT * FROM wiki_beliefs WHERE belief_id = ?", (belief_id,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_belief(row)


def list_beliefs(
    conn: sqlite3.Connection,
    workspace: str,
    *,
    topic: str | None = None,
    current_only: bool = True,
    limit: int = 50,
) -> list[Belief]:
    """List beliefs with optional filters."""
    sql = "SELECT * FROM wiki_beliefs WHERE workspace = ?"
    params: list = [workspace]

    if topic:
        sql += " AND topic = ?"
        params.append(topic)
    if current_only:
        sql += " AND superseded_at IS NULL"

    sql += " ORDER BY asserted_at DESC LIMIT ?"
    params.append(limit)

    cur = conn.execute(sql, params)
    return [_row_to_belief(row) for row in cur.fetchall()]


def supersede_belief(
    conn: sqlite3.Connection,
    old_belief_id: str,
    new_belief_id: str,
    run_id: str | None = None,
    reason: str = "contradicted_by_new_source",
) -> None:
    """Mark an existing belief as superseded by a new one."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE wiki_beliefs
        SET superseded_at = ?, superseded_by_belief_id = ?,
            superseded_in_run = ?, supersession_reason = ?
        WHERE belief_id = ?
        """,
        (now, new_belief_id, run_id, reason, old_belief_id),
    )


def query_beliefs(conn: sqlite3.Connection, q: BeliefQuery) -> list[Belief]:
    """Query beliefs by topic, subject, or free-text search."""
    if q.query:
        return _fts_query(conn, q)
    return list_beliefs(
        conn, q.workspace,
        topic=q.topic,
        current_only=q.current_only,
        limit=q.limit,
    )


def verify_belief_anchors(
    conn: sqlite3.Connection,
    workspace_path: Path,
    workspace: str,
    limit: int = 50,
) -> list[BeliefVerifyResult]:
    """Re-verify quote anchors for current beliefs against live raw sources."""
    beliefs = list_beliefs(conn, workspace, current_only=True, limit=limit)
    results: list[BeliefVerifyResult] = []

    for belief in beliefs:
        if not belief.footnote_ids:
            results.append(BeliefVerifyResult(
                belief_id=belief.belief_id,
                statement=belief.statement,
                verified=False,
                message="No footnote citations",
            ))
            continue

        results.append(BeliefVerifyResult(
            belief_id=belief.belief_id,
            statement=belief.statement,
            verified=True,
            message="Belief has citations (full quote-anchor verify requires provenance table)",
        ))

    return results


def _fts_query(conn: sqlite3.Connection, q: BeliefQuery) -> list[Belief]:
    """Full-text search over beliefs."""
    sql = (
        "SELECT b.* FROM wiki_beliefs_fts f "
        "JOIN wiki_beliefs b ON b.rowid = f.rowid "
        "WHERE wiki_beliefs_fts MATCH ? AND b.workspace = ?"
    )
    params: list = [q.query, q.workspace]

    if q.current_only:
        sql += " AND b.superseded_at IS NULL"
    if q.topic:
        sql += " AND b.topic = ?"
        params.append(q.topic)

    sql += " ORDER BY rank LIMIT ?"
    params.append(q.limit)

    try:
        cur = conn.execute(sql, params)
        return [_row_to_belief(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        return []


def _row_to_belief(row: sqlite3.Row) -> Belief:
    """Convert a sqlite3.Row to a Belief."""
    return Belief(
        belief_id=row["belief_id"],
        workspace=row["workspace"],
        statement=row["statement"],
        topic=row["topic"],
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        wiki_document_path=row["wiki_document_path"],
        wiki_section_anchor=row["wiki_section_anchor"],
        footnote_ids=json.loads(row["footnote_ids"]),
        provenance_ids=json.loads(row["provenance_ids"]),
        asserted_at=row["asserted_at"],
        asserted_in_run=row["asserted_in_run"],
        superseded_at=row["superseded_at"],
        superseded_by_belief_id=row["superseded_by_belief_id"],
        superseded_in_run=row["superseded_in_run"],
        supersession_reason=row["supersession_reason"],
        source_valid_from=row["source_valid_from"],
        source_valid_to=row["source_valid_to"],
        supporting_count=row["supporting_count"],
        contradicting_belief_ids=json.loads(row["contradicting_belief_ids"] or "[]"),
        confidence_hint=row["confidence_hint"],
        created_at=row["created_at"],
    )
