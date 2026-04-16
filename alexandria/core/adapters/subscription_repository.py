"""Subscription item repository — CRUD over subscription_items table."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SubscriptionItem:
    """A single subscription queue item."""

    item_id: str
    workspace: str
    source_id: str | None
    adapter_type: str
    external_id: str | None
    title: str
    author: str | None
    url: str | None
    published_at: str | None
    content_path: str
    content_hash: str
    excerpt: str | None
    metadata: dict[str, Any]
    status: str
    ingested_at: str | None
    dismissed_at: str | None
    created_at: str


def insert_subscription_item(
    conn: sqlite3.Connection,
    workspace: str,
    source_id: str | None,
    adapter_type: str,
    title: str,
    content_path: str,
    content_hash: str,
    *,
    external_id: str | None = None,
    author: str | None = None,
    url: str | None = None,
    published_at: str | None = None,
    excerpt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Insert a subscription item. Returns item_id."""
    item_id = f"sub-{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO subscription_items
          (item_id, workspace, source_id, adapter_type, external_id, title,
           author, url, published_at, content_path, content_hash, excerpt,
           metadata, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (
            item_id, workspace, source_id, adapter_type, external_id, title,
            author, url, published_at, content_path, content_hash, excerpt,
            json.dumps(metadata or {}), now,
        ),
    )
    return item_id


def is_duplicate(
    conn: sqlite3.Connection,
    workspace: str,
    external_id: str | None,
    content_hash: str,
) -> bool:
    """Check if an item with the same external_id + content_hash exists."""
    if external_id:
        row = conn.execute(
            """SELECT 1 FROM subscription_items
            WHERE workspace = ? AND external_id = ? AND content_hash = ?""",
            (workspace, external_id, content_hash),
        ).fetchone()
        return row is not None
    return False


def list_subscription_items(
    conn: sqlite3.Connection,
    workspace: str,
    status: str | None = None,
    adapter_type: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[SubscriptionItem]:
    """List subscription items with optional filters."""
    clauses = ["workspace = ?"]
    params: list[Any] = [workspace]

    if status:
        clauses.append("status = ?")
        params.append(status)
    if adapter_type:
        clauses.append("adapter_type = ?")
        params.append(adapter_type)
    if since:
        clauses.append("published_at >= ?")
        params.append(since)

    where = " AND ".join(clauses)
    params.append(limit)
    rows = conn.execute(
        f"""SELECT * FROM subscription_items
        WHERE {where} ORDER BY published_at DESC LIMIT ?""",
        params,
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def get_subscription_item(
    conn: sqlite3.Connection, item_id: str
) -> SubscriptionItem | None:
    row = conn.execute(
        "SELECT * FROM subscription_items WHERE item_id = ?", (item_id,)
    ).fetchone()
    return _row_to_item(row) if row else None


def mark_ingested(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute(
        "UPDATE subscription_items SET status = 'ingested', ingested_at = ? WHERE item_id = ?",
        (datetime.now(timezone.utc).isoformat(), item_id),
    )


def mark_dismissed(conn: sqlite3.Connection, item_id: str) -> None:
    conn.execute(
        "UPDATE subscription_items SET status = 'dismissed', dismissed_at = ? WHERE item_id = ?",
        (datetime.now(timezone.utc).isoformat(), item_id),
    )


def _row_to_item(row: sqlite3.Row) -> SubscriptionItem:
    return SubscriptionItem(
        item_id=row["item_id"],
        workspace=row["workspace"],
        source_id=row["source_id"],
        adapter_type=row["adapter_type"],
        external_id=row["external_id"],
        title=row["title"],
        author=row["author"],
        url=row["url"],
        published_at=row["published_at"],
        content_path=row["content_path"],
        content_hash=row["content_hash"],
        excerpt=row["excerpt"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        status=row["status"],
        ingested_at=row["ingested_at"],
        dismissed_at=row["dismissed_at"],
        created_at=row["created_at"],
    )
