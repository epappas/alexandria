"""Source adapter and source_runs SQLite repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class SourceConfig:
    """A configured source adapter row."""

    source_id: str
    workspace: str
    adapter_type: str
    name: str
    config_json: dict[str, Any]
    enabled: bool
    created_at: str
    updated_at: str


@dataclass
class SourceRun:
    """A single source sync run row."""

    source_run_id: str
    source_id: str
    run_id: str | None
    status: str
    started_at: str
    ended_at: str | None
    items_synced: int
    items_errored: int
    error_message: str | None
    triggered_by: str


def insert_source(
    conn: sqlite3.Connection,
    workspace: str,
    adapter_type: str,
    name: str,
    config: dict[str, Any],
) -> str:
    """Insert a new source adapter. Returns source_id."""
    source_id = f"src-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO source_adapters
          (source_id, workspace, adapter_type, name, config_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_id, workspace, adapter_type, name, json.dumps(config), now, now),
    )
    return source_id


def get_source(conn: sqlite3.Connection, source_id: str) -> SourceConfig | None:
    row = conn.execute(
        "SELECT * FROM source_adapters WHERE source_id = ?", (source_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_source(row)


def list_sources(
    conn: sqlite3.Connection, workspace: str, enabled_only: bool = False
) -> list[SourceConfig]:
    sql = "SELECT * FROM source_adapters WHERE workspace = ?"
    params: list[Any] = [workspace]
    if enabled_only:
        sql += " AND enabled = 1"
    sql += " ORDER BY name"
    return [_row_to_source(r) for r in conn.execute(sql, params).fetchall()]


def remove_source(conn: sqlite3.Connection, source_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM source_adapters WHERE source_id = ?", (source_id,)
    )
    return cur.rowcount > 0


def toggle_source(conn: sqlite3.Connection, source_id: str, enabled: bool) -> None:
    conn.execute(
        "UPDATE source_adapters SET enabled = ?, updated_at = ? WHERE source_id = ?",
        (int(enabled), datetime.now(UTC).isoformat(), source_id),
    )


# -- Source runs ----------------------------------------------------------------


def create_source_run(
    conn: sqlite3.Connection,
    source_id: str,
    run_id: str | None = None,
    triggered_by: str = "cli:sync",
) -> str:
    """Create a new source_run row. Returns source_run_id."""
    source_run_id = f"srun-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO source_runs
          (source_run_id, source_id, run_id, status, started_at, triggered_by)
        VALUES (?, ?, ?, 'running', ?, ?)""",
        (source_run_id, source_id, run_id, now, triggered_by),
    )
    return source_run_id


def complete_source_run(
    conn: sqlite3.Connection,
    source_run_id: str,
    items_synced: int,
    items_errored: int,
    error_message: str | None = None,
) -> None:
    """Mark a source run as completed or failed."""
    status = "failed" if items_errored > 0 and items_synced == 0 else "completed"
    conn.execute(
        """UPDATE source_runs
        SET status = ?, ended_at = ?, items_synced = ?, items_errored = ?, error_message = ?
        WHERE source_run_id = ?""",
        (
            status,
            datetime.now(UTC).isoformat(),
            items_synced,
            items_errored,
            error_message,
            source_run_id,
        ),
    )


def sweep_orphaned_source_runs(conn: sqlite3.Connection) -> int:
    """Transition any 'running' or 'pending' source_runs to 'abandoned'."""
    cur = conn.execute(
        """UPDATE source_runs
        SET status = 'abandoned', ended_at = ?, error_message = 'orphan sweep'
        WHERE status IN ('running', 'pending')""",
        (datetime.now(UTC).isoformat(),),
    )
    return cur.rowcount


def list_source_runs(
    conn: sqlite3.Connection, source_id: str, limit: int = 10
) -> list[SourceRun]:
    rows = conn.execute(
        """SELECT * FROM source_runs
        WHERE source_id = ?
        ORDER BY started_at DESC LIMIT ?""",
        (source_id, limit),
    ).fetchall()
    return [_row_to_run(r) for r in rows]


# -- Row mappers ----------------------------------------------------------------


def _row_to_source(row: sqlite3.Row) -> SourceConfig:
    return SourceConfig(
        source_id=row["source_id"],
        workspace=row["workspace"],
        adapter_type=row["adapter_type"],
        name=row["name"],
        config_json=json.loads(row["config_json"]) if row["config_json"] else {},
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_run(row: sqlite3.Row) -> SourceRun:
    return SourceRun(
        source_run_id=row["source_run_id"],
        source_id=row["source_id"],
        run_id=row["run_id"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        items_synced=row["items_synced"],
        items_errored=row["items_errored"],
        error_message=row["error_message"],
        triggered_by=row["triggered_by"],
    )
