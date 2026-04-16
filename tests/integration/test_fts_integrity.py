"""FTS5 integrity tests against a real SQLite database."""

from __future__ import annotations

from pathlib import Path

from alexandria.core.fts_integrity import check_fts_integrity, rebuild_fts
from alexandria.db.connection import connect, db_path


def test_fts_integrity_ok_on_empty_database(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        report = check_fts_integrity(conn)
    assert report.status == "ok"
    assert report.content_rows == 0
    assert report.fts_rows == 0


def test_fts_stays_in_sync_on_insert(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO documents
              (id, workspace, layer, path, filename, title, file_type,
               content, content_hash, size_bytes, tags, created_at, updated_at)
            VALUES ('id1', 'global', 'raw', '/raw/local/', 'a.md', 'A',
                    'md', 'hello world', 'hash1', 11, '[]', '2026-04-16', '2026-04-16')
            """
        )
        conn.execute("COMMIT")
        report = check_fts_integrity(conn)
    assert report.status == "ok"
    assert report.content_rows == 1
    assert report.fts_rows == 1


def test_fts_search_finds_inserted_content(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO documents
              (id, workspace, layer, path, filename, title, file_type,
               content, content_hash, size_bytes, tags, created_at, updated_at)
            VALUES ('id2', 'global', 'raw', '/raw/local/', 'b.md', 'B',
                    'md', 'the cat sat on the mat', 'hash2', 22, '[]',
                    '2026-04-16', '2026-04-16')
            """
        )
        conn.execute("COMMIT")
        cur = conn.execute(
            "SELECT title FROM documents_fts WHERE documents_fts MATCH 'cat'"
        )
        row = cur.fetchone()
    assert row is not None
    assert row["title"] == "B"


def test_rebuild_fts_runs_without_error(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        rebuild_fts(conn)
        report = check_fts_integrity(conn)
    assert report.status == "ok"
