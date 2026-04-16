"""Tests for source adapter and source_runs repository."""

import pytest

from alexandria.core.adapters.source_repository import (
    SourceConfig,
    complete_source_run,
    create_source_run,
    get_source,
    insert_source,
    list_source_runs,
    list_sources,
    remove_source,
    sweep_orphaned_source_runs,
    toggle_source,
)
from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


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


class TestSourceRepository:
    def test_insert_and_get(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "local", "My Docs", {"path": "/docs"})
        conn.execute("COMMIT")
        assert sid.startswith("src-")

        src = get_source(conn, sid)
        assert src is not None
        assert src.name == "My Docs"
        assert src.adapter_type == "local"

    def test_list_sources(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_source(conn, "test", "local", "A", {})
        insert_source(conn, "test", "github", "B", {})
        conn.execute("COMMIT")

        sources = list_sources(conn, "test")
        assert len(sources) == 2

    def test_list_enabled_only(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "local", "A", {})
        insert_source(conn, "test", "github", "B", {})
        conn.execute("COMMIT")

        toggle_source(conn, sid, False)
        enabled = list_sources(conn, "test", enabled_only=True)
        assert len(enabled) == 1

    def test_remove_source(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "local", "A", {})
        conn.execute("COMMIT")

        conn.execute("BEGIN IMMEDIATE")
        assert remove_source(conn, sid) is True
        conn.execute("COMMIT")

        assert get_source(conn, sid) is None

    def test_source_run_lifecycle(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "local", "A", {})
        conn.execute("COMMIT")

        conn.execute("BEGIN IMMEDIATE")
        srun_id = create_source_run(conn, sid)
        conn.execute("COMMIT")

        conn.execute("BEGIN IMMEDIATE")
        complete_source_run(conn, srun_id, items_synced=10, items_errored=0)
        conn.execute("COMMIT")

        runs = list_source_runs(conn, sid)
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].items_synced == 10

    def test_orphan_sweep(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "local", "A", {})
        create_source_run(conn, sid)
        create_source_run(conn, sid)
        conn.execute("COMMIT")

        swept = sweep_orphaned_source_runs(conn)
        assert swept == 2

        runs = list_source_runs(conn, sid)
        assert all(r.status == "abandoned" for r in runs)
