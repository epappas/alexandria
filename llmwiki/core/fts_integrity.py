"""FTS5 integrity verification.

Reflects mlops-engineer Finding #4 from `docs/research/reviews/plan/03_mlops_engineer.md`.
External-content FTS5 tables can desync silently from the source table after
a crash, partial WAL replay, or a malformed trigger. Phase 0 ships the cheap
native check (FTS5's built-in ``integrity-check`` command + a row-count
comparison) so users don't run blind for months.

The expensive content-hash comparison still arrives in Phase 11.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FtsIntegrityReport:
    """Result of an FTS integrity check."""

    table: str
    fts_table: str
    status: Literal["ok", "row_count_mismatch", "fts_internal_error"]
    content_rows: int
    fts_rows: int
    error_message: str | None = None


def check_fts_integrity(
    conn: sqlite3.Connection,
    *,
    table: str = "documents",
    fts_table: str = "documents_fts",
) -> FtsIntegrityReport:
    """Run two checks:

    1. Row count: compare ``COUNT(*) FROM table`` and ``COUNT(*) FROM fts_table``.
    2. FTS5 native integrity: ``INSERT INTO fts_table(fts_table) VALUES('integrity-check')``.

    The native integrity-check raises a ``sqlite3.DatabaseError`` if FTS state is
    corrupt; we capture and report it.
    """
    if not _table_exists(conn, table):
        return FtsIntegrityReport(
            table=table,
            fts_table=fts_table,
            status="ok",
            content_rows=0,
            fts_rows=0,
            error_message=f"table {table!r} does not exist (nothing to check)",
        )
    if not _table_exists(conn, fts_table):
        return FtsIntegrityReport(
            table=table,
            fts_table=fts_table,
            status="fts_internal_error",
            content_rows=0,
            fts_rows=0,
            error_message=f"fts table {fts_table!r} does not exist",
        )

    content_rows = _row_count(conn, table)
    fts_rows = _row_count(conn, fts_table)

    try:
        conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('integrity-check')")
    except sqlite3.DatabaseError as exc:
        return FtsIntegrityReport(
            table=table,
            fts_table=fts_table,
            status="fts_internal_error",
            content_rows=content_rows,
            fts_rows=fts_rows,
            error_message=str(exc),
        )

    if content_rows != fts_rows:
        return FtsIntegrityReport(
            table=table,
            fts_table=fts_table,
            status="row_count_mismatch",
            content_rows=content_rows,
            fts_rows=fts_rows,
            error_message=f"{table}={content_rows}, {fts_table}={fts_rows}",
        )

    return FtsIntegrityReport(
        table=table,
        fts_table=fts_table,
        status="ok",
        content_rows=content_rows,
        fts_rows=fts_rows,
    )


def rebuild_fts(
    conn: sqlite3.Connection,
    *,
    fts_table: str = "documents_fts",
) -> None:
    """Force a full FTS5 rebuild. O(N) but always correct."""
    conn.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('rebuild')")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


def _row_count(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM {name}")
    row = cur.fetchone()
    return int(row[0]) if row else 0
