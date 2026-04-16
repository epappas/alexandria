"""Tests for Phase 4 database migrations (0004 sources, 0005 events)."""

import sqlite3

import pytest

from llmwiki.db.connection import connect
from llmwiki.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


class TestPhase4Migrations:
    def test_fresh_migration_creates_all_tables(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "source_adapters" in tables
            assert "source_runs" in tables
            assert "events" in tables

    def test_source_adapters_insert(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)

            # Need a workspace first
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO source_adapters "
                "(source_id, workspace, adapter_type, name, config_json, created_at, updated_at) "
                "VALUES ('src-1', 'test', 'local', 'My Local', '{}', '2025-01-01', '2025-01-01')"
            )
            conn.execute("COMMIT")

            row = conn.execute(
                "SELECT * FROM source_adapters WHERE source_id = 'src-1'"
            ).fetchone()
            assert row["name"] == "My Local"
            assert row["adapter_type"] == "local"

    def test_source_runs_insert(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)

            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO source_adapters "
                "(source_id, workspace, adapter_type, name, config_json, created_at, updated_at) "
                "VALUES ('src-1', 'test', 'github', 'GH', '{}', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO source_runs "
                "(source_run_id, source_id, status, started_at, triggered_by) "
                "VALUES ('srun-1', 'src-1', 'running', '2025-01-01', 'cli:sync')"
            )
            conn.execute("COMMIT")

            row = conn.execute(
                "SELECT * FROM source_runs WHERE source_run_id = 'srun-1'"
            ).fetchone()
            assert row["status"] == "running"

    def test_events_insert_and_fts(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)

            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
            )
            conn.execute(
                "INSERT INTO events "
                "(event_id, workspace, source_type, event_type, title, body, "
                "event_data, occurred_at, ingested_at) "
                "VALUES ('ev-1', 'test', 'github', 'issue', 'Fix auth bug', "
                "'Detailed description of auth fix', '{}', '2025-01-01', '2025-01-01')"
            )
            conn.execute("COMMIT")

            # Test FTS search
            rows = conn.execute(
                "SELECT e.* FROM events_fts "
                "JOIN events e ON events_fts.rowid = e.rowid "
                "WHERE events_fts MATCH 'auth'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["title"] == "Fix auth bug"

    def test_adapter_type_constraint(self, db_path) -> None:
        with connect(db_path) as conn:
            Migrator().apply_pending(conn)

            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
                "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO source_adapters "
                    "(source_id, workspace, adapter_type, name, config_json, created_at, updated_at) "
                    "VALUES ('src-1', 'test', 'invalid_type', 'Bad', '{}', '2025-01-01', '2025-01-01')"
                )
            conn.execute("ROLLBACK")

    def test_upgrade_from_phase3(self, db_path) -> None:
        """Test applying 0004+0005 on top of existing 0001+0002+0003."""
        with connect(db_path) as conn:
            migrator = Migrator()
            applied = migrator.apply_pending(conn)
            # All 5 migrations should apply
            assert 4 in applied
            assert 5 in applied

            # Re-run should be a no-op
            second = migrator.apply_pending(conn)
            assert second == []
