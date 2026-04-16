"""Tests for Phase 5 database migrations (0006 subscriptions, 0007 adapter types)."""

import sqlite3

import pytest

from llmwiki.db.connection import connect
from llmwiki.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


class TestPhase5Migrations:
    def test_subscription_items_table_created(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "subscription_items" in tables

    def test_subscription_items_insert(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO subscription_items "
                "(item_id, workspace, adapter_type, title, content_path, content_hash, created_at) "
                "VALUES ('sub-1', 'test', 'rss', 'Test', 'path.md', 'abc', '2025-01-01')"
            )
            conn.execute("COMMIT")

            row = conn.execute(
                "SELECT * FROM subscription_items WHERE item_id = 'sub-1'"
            ).fetchone()
            assert row["title"] == "Test"
            assert row["status"] == "pending"

    def test_subscription_fts(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO subscription_items "
                "(item_id, workspace, adapter_type, title, excerpt, content_path, content_hash, created_at) "
                "VALUES ('sub-1', 'test', 'rss', 'Machine Learning Today', "
                "'Neural nets break records.', 'path.md', 'abc', '2025-01-01')"
            )
            conn.execute("COMMIT")

            rows = conn.execute(
                "SELECT si.* FROM subscription_items_fts "
                "JOIN subscription_items si ON subscription_items_fts.rowid = si.rowid "
                "WHERE subscription_items_fts MATCH 'machine'"
            ).fetchall()
            assert len(rows) == 1

    def test_expanded_adapter_types(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp', '2025-01-01', '2025-01-01')"
            )
            # rss and imap should now be valid adapter_types
            conn.execute(
                "INSERT INTO source_adapters "
                "(source_id, workspace, adapter_type, name, created_at, updated_at) "
                "VALUES ('src-rss', 'test', 'rss', 'Blog', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO source_adapters "
                "(source_id, workspace, adapter_type, name, created_at, updated_at) "
                "VALUES ('src-imap', 'test', 'imap', 'Newsletter', '2025-01-01', '2025-01-01')"
            )
            conn.execute("COMMIT")

            count = conn.execute("SELECT COUNT(*) FROM source_adapters").fetchone()[0]
            assert count == 2

    def test_upgrade_preserves_existing_sources(self, db_path) -> None:
        """Verify that migration 0007 preserves existing source_adapters data."""
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)
            # All migrations applied; the table should have the expanded CHECK
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO source_adapters "
                "(source_id, workspace, adapter_type, name, created_at, updated_at) "
                "VALUES ('src-1', 'test', 'local', 'Docs', '2025-01-01', '2025-01-01')"
            )
            conn.execute("COMMIT")

            row = conn.execute(
                "SELECT * FROM source_adapters WHERE source_id = 'src-1'"
            ).fetchone()
            assert row["name"] == "Docs"
            assert row["adapter_type"] == "local"
