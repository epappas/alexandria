"""SQLite connection helpers.

Every connection runs in WAL mode with foreign keys enabled and a 5-second
busy timeout. The ``connect`` helper returns a context manager so callers do
not leak file handles.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

DB_FILENAME = "state.db"


def db_path(home: Path) -> Path:
    """Return the absolute path to the llmwiki SQLite file."""
    return home / DB_FILENAME


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with WAL mode + foreign keys + busy timeout.

    The connection is committed on a clean exit and rolled back on exception.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        isolation_level=None,  # we manage transactions ourselves
        timeout=5.0,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
    finally:
        conn.close()


def fetch_user_version(conn: sqlite3.Connection) -> int:
    """Return the current ``PRAGMA user_version`` value."""
    cur = conn.execute("PRAGMA user_version")
    row = cur.fetchone()
    return int(row[0]) if row else 0


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    """Write the ``PRAGMA user_version`` value (must be a literal int)."""
    if not isinstance(version, int) or version < 0:
        raise ValueError(f"version must be a non-negative int, got {version!r}")
    conn.execute(f"PRAGMA user_version = {version}")
