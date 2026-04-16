"""Event repository for storing and querying source events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from llmwiki.core.adapters.base import FetchedItem


@dataclass
class EventQuery:
    """Filter criteria for event searches."""

    workspace: str
    source_type: str | None = None
    event_type: str | None = None
    query: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int = 50


@dataclass
class Event:
    """A stored event row."""

    event_id: str
    workspace: str
    source_id: str | None
    source_type: str
    event_type: str
    title: str
    body: str | None
    url: str | None
    author: str | None
    event_data: dict[str, Any]
    occurred_at: str
    ingested_at: str


def insert_event(
    conn: sqlite3.Connection,
    workspace: str,
    source_id: str | None,
    item: FetchedItem,
) -> str:
    """Insert a FetchedItem as an event row. Returns the event_id."""
    event_id = f"ev-{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO events
          (event_id, workspace, source_id, source_type, event_type,
           title, body, url, author, event_data, occurred_at, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            workspace,
            source_id,
            item.source_type,
            item.event_type,
            item.title,
            item.body,
            item.url,
            item.author,
            json.dumps(item.event_data),
            item.occurred_at or now,
            now,
        ),
    )
    return event_id


def query_events(conn: sqlite3.Connection, q: EventQuery) -> list[Event]:
    """Query events with optional filters and FTS search."""
    if q.query:
        return _fts_query(conn, q)
    return _sql_query(conn, q)


def _sql_query(conn: sqlite3.Connection, q: EventQuery) -> list[Event]:
    clauses = ["workspace = ?"]
    params: list[Any] = [q.workspace]

    if q.source_type:
        clauses.append("source_type = ?")
        params.append(q.source_type)
    if q.event_type:
        clauses.append("event_type = ?")
        params.append(q.event_type)
    if q.since:
        clauses.append("occurred_at >= ?")
        params.append(q.since)
    if q.until:
        # If date-only (no 'T'), append end-of-day to include full day
        until_val = q.until if "T" in q.until else q.until + "T23:59:59Z"
        clauses.append("occurred_at <= ?")
        params.append(until_val)

    where = " AND ".join(clauses)
    params.append(q.limit)
    sql = f"""SELECT event_id, workspace, source_id, source_type, event_type,
                     title, body, url, author, event_data, occurred_at, ingested_at
              FROM events WHERE {where}
              ORDER BY occurred_at DESC LIMIT ?"""

    return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]


def _fts_query(conn: sqlite3.Connection, q: EventQuery) -> list[Event]:
    clauses = ["e.workspace = ?"]
    params: list[Any] = [q.workspace]

    if q.source_type:
        clauses.append("e.source_type = ?")
        params.append(q.source_type)
    if q.event_type:
        clauses.append("e.event_type = ?")
        params.append(q.event_type)
    if q.since:
        clauses.append("e.occurred_at >= ?")
        params.append(q.since)
    if q.until:
        until_val = q.until if "T" in q.until else q.until + "T23:59:59Z"
        clauses.append("e.occurred_at <= ?")
        params.append(until_val)

    where = " AND ".join(clauses)
    params.insert(0, q.query)  # MATCH param comes first
    params.append(q.limit)

    sql = f"""SELECT e.event_id, e.workspace, e.source_id, e.source_type, e.event_type,
                     e.title, e.body, e.url, e.author, e.event_data, e.occurred_at, e.ingested_at
              FROM events_fts
              JOIN events e ON events_fts.rowid = e.rowid
              WHERE events_fts MATCH ? AND {where}
              ORDER BY e.occurred_at DESC LIMIT ?"""

    return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        event_id=row["event_id"],
        workspace=row["workspace"],
        source_id=row["source_id"],
        source_type=row["source_type"],
        event_type=row["event_type"],
        title=row["title"],
        body=row["body"],
        url=row["url"],
        author=row["author"],
        event_data=json.loads(row["event_data"]) if row["event_data"] else {},
        occurred_at=row["occurred_at"],
        ingested_at=row["ingested_at"],
    )
