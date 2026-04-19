"""Daemon heartbeat management.

Children write heartbeats every 5 seconds. Parent checks every 15 seconds
and marks children missing 3+ consecutive beats (45s) as failed.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

HEARTBEAT_INTERVAL = 5.0  # seconds between child heartbeats
CHECK_INTERVAL = 15.0     # seconds between parent checks
MISS_THRESHOLD = 3        # missed beats before marking failed
DEADLINE = timedelta(seconds=HEARTBEAT_INTERVAL * MISS_THRESHOLD)


def record_heartbeat(
    conn: sqlite3.Connection,
    child_name: str,
    pid: int,
    state: str = "running",
) -> None:
    """Upsert a heartbeat for a child process."""
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO daemon_heartbeats (child_name, pid, started_at, last_beat, state)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(child_name) DO UPDATE SET
          pid = excluded.pid,
          last_beat = excluded.last_beat,
          state = excluded.state""",
        (child_name, pid, now, now, state),
    )


def check_heartbeats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Check for stale heartbeats. Returns list of dead children."""
    cutoff = (datetime.now(UTC) - DEADLINE).isoformat()
    rows = conn.execute(
        """SELECT child_name, pid, last_beat, state FROM daemon_heartbeats
        WHERE last_beat < ? AND state NOT IN ('failed', 'draining')""",
        (cutoff,),
    ).fetchall()

    dead: list[dict[str, Any]] = []
    for row in rows:
        conn.execute(
            "UPDATE daemon_heartbeats SET state = 'failed' WHERE child_name = ?",
            (row["child_name"],),
        )
        dead.append({
            "child_name": row["child_name"],
            "pid": row["pid"],
            "last_beat": row["last_beat"],
        })
    return dead


def clear_heartbeats(conn: sqlite3.Connection) -> None:
    """Clear all heartbeat entries (called on daemon startup)."""
    conn.execute("DELETE FROM daemon_heartbeats")


def get_heartbeats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Get all current heartbeat entries."""
    rows = conn.execute(
        "SELECT child_name, pid, started_at, last_beat, state FROM daemon_heartbeats"
    ).fetchall()
    return [dict(row) for row in rows]
