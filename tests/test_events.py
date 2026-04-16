"""Tests for event storage and query."""

import sqlite3

import pytest

from llmwiki.core.adapters.base import FetchedItem
from llmwiki.core.adapters.events import Event, EventQuery, insert_event, query_events
from llmwiki.db.connection import connect
from llmwiki.db.migrator import Migrator


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


class TestEvents:
    def test_insert_and_query(self, conn) -> None:
        item = FetchedItem(
            source_type="github",
            event_type="issue",
            title="Fix auth bug",
            body="The auth module has a critical bug.",
            author="alice",
            occurred_at="2025-03-15T10:00:00Z",
        )
        conn.execute("BEGIN IMMEDIATE")
        event_id = insert_event(conn, "test", None, item)
        conn.execute("COMMIT")
        assert event_id.startswith("ev-")

        results = query_events(conn, EventQuery(workspace="test"))
        assert len(results) == 1
        assert results[0].title == "Fix auth bug"

    def test_query_by_source_type(self, conn) -> None:
        for st in ("github", "github", "git-local"):
            conn.execute("BEGIN IMMEDIATE")
            insert_event(conn, "test", None, FetchedItem(
                source_type=st, event_type="test", title=f"Event from {st}",
                occurred_at="2025-03-15T10:00:00Z",
            ))
            conn.execute("COMMIT")

        results = query_events(conn, EventQuery(workspace="test", source_type="github"))
        assert len(results) == 2

    def test_query_by_date_range(self, conn) -> None:
        for date in ("2025-01-01", "2025-06-15", "2025-12-31"):
            conn.execute("BEGIN IMMEDIATE")
            insert_event(conn, "test", None, FetchedItem(
                source_type="local", event_type="file_sync",
                title=f"Event on {date}", occurred_at=f"{date}T00:00:00Z",
            ))
            conn.execute("COMMIT")

        results = query_events(conn, EventQuery(
            workspace="test", since="2025-06-01", until="2025-12-31",
        ))
        assert len(results) == 2

    def test_fts_search(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_event(conn, "test", None, FetchedItem(
            source_type="github", event_type="issue",
            title="Refactor authentication module",
            body="Complete rewrite of auth using JWT.",
            occurred_at="2025-03-15T10:00:00Z",
        ))
        insert_event(conn, "test", None, FetchedItem(
            source_type="github", event_type="issue",
            title="Fix database connection pooling",
            body="Pool was leaking connections.",
            occurred_at="2025-03-16T10:00:00Z",
        ))
        conn.execute("COMMIT")

        results = query_events(conn, EventQuery(workspace="test", query="authentication"))
        assert len(results) == 1
        assert "authentication" in results[0].title

    def test_empty_workspace(self, conn) -> None:
        results = query_events(conn, EventQuery(workspace="other"))
        assert results == []
