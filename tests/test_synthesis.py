"""Tests for temporal synthesis."""

from pathlib import Path

import pytest

from alexandria.core.synthesis import run_synthesis
from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def workspace_path(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def conn(db_path):
    with connect(db_path) as c:
        Migrator().apply_pending(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
        )
        c.execute("COMMIT")
        yield c


class TestSynthesis:
    def test_no_activity_skipped(self, conn, workspace_path) -> None:
        result = run_synthesis(conn, "test", workspace_path)
        assert result["status"] == "skipped"

    def test_dry_run(self, conn, workspace_path) -> None:
        # Insert some events
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO events (event_id, workspace, source_type, event_type, "
            "title, event_data, occurred_at, ingested_at) "
            "VALUES ('ev-1', 'test', 'github', 'commit', 'Fix auth', '{}', "
            "datetime('now'), datetime('now'))"
        )
        conn.execute("COMMIT")

        result = run_synthesis(conn, "test", workspace_path, dry_run=True)
        assert result["status"] == "dry_run"
        assert result["events_count"] >= 1

    def test_full_synthesis(self, conn, workspace_path) -> None:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO events (event_id, workspace, source_type, event_type, "
            "title, event_data, occurred_at, ingested_at) "
            "VALUES ('ev-1', 'test', 'local', 'file_sync', 'New doc', '{}', "
            "datetime('now'), datetime('now'))"
        )
        conn.execute("COMMIT")

        result = run_synthesis(conn, "test", workspace_path)
        assert result["status"] == "completed"
        assert result["output_path"]

        # Verify file written
        out_path = workspace_path / result["output_path"]
        assert out_path.exists()
        content = out_path.read_text()
        assert "Weekly Digest" in content
