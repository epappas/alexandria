"""Tests for subscription item repository."""

import pytest

from alexandria.core.adapters.subscription_repository import (
    get_subscription_item,
    insert_subscription_item,
    is_duplicate,
    list_subscription_items,
    mark_dismissed,
    mark_ingested,
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


class TestSubscriptionRepository:
    def test_insert_and_get(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        item_id = insert_subscription_item(
            conn, "test", None, "rss", "Test Post",
            "raw/subscriptions/test.md", "abc123",
            external_id="guid-1", author="Alice",
        )
        conn.execute("COMMIT")

        item = get_subscription_item(conn, item_id)
        assert item is not None
        assert item.title == "Test Post"
        assert item.status == "pending"
        assert item.external_id == "guid-1"

    def test_list_pending(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_subscription_item(conn, "test", None, "rss", "A", "a.md", "h1")
        insert_subscription_item(conn, "test", None, "rss", "B", "b.md", "h2")
        conn.execute("COMMIT")

        items = list_subscription_items(conn, "test", status="pending")
        assert len(items) == 2

    def test_list_by_adapter(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_subscription_item(conn, "test", None, "rss", "RSS Item", "a.md", "h1")
        insert_subscription_item(conn, "test", None, "imap", "Email Item", "b.md", "h2")
        conn.execute("COMMIT")

        rss_items = list_subscription_items(conn, "test", adapter_type="rss")
        assert len(rss_items) == 1
        assert rss_items[0].title == "RSS Item"

    def test_mark_ingested(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        item_id = insert_subscription_item(conn, "test", None, "rss", "A", "a.md", "h1")
        conn.execute("COMMIT")

        mark_ingested(conn, item_id)
        item = get_subscription_item(conn, item_id)
        assert item.status == "ingested"
        assert item.ingested_at is not None

    def test_mark_dismissed(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        item_id = insert_subscription_item(conn, "test", None, "rss", "A", "a.md", "h1")
        conn.execute("COMMIT")

        mark_dismissed(conn, item_id)
        item = get_subscription_item(conn, item_id)
        assert item.status == "dismissed"
        assert item.dismissed_at is not None

    def test_dedup_by_external_id_and_hash(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_subscription_item(
            conn, "test", None, "rss", "A", "a.md", "hash1",
            external_id="guid-1",
        )
        conn.execute("COMMIT")

        # Same external_id + same hash -> duplicate
        assert is_duplicate(conn, "test", "guid-1", "hash1") is True

        # Same external_id + different hash -> not duplicate (content changed)
        assert is_duplicate(conn, "test", "guid-1", "hash2") is False

        # Different external_id -> not duplicate
        assert is_duplicate(conn, "test", "guid-2", "hash1") is False

    def test_dedup_no_external_id(self, conn) -> None:
        # Without external_id, dedup doesn't apply
        assert is_duplicate(conn, "test", None, "hash1") is False

    def test_fts_search(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_subscription_item(
            conn, "test", None, "rss", "Machine Learning Advances",
            "a.md", "h1", excerpt="Neural networks achieve new benchmark.",
        )
        insert_subscription_item(
            conn, "test", None, "rss", "Cooking Tips",
            "b.md", "h2", excerpt="Best pasta recipe.",
        )
        conn.execute("COMMIT")

        # FTS search
        rows = conn.execute(
            "SELECT si.* FROM subscription_items_fts fts "
            "JOIN subscription_items si ON fts.rowid = si.rowid "
            "WHERE subscription_items_fts MATCH 'machine'"
        ).fetchall()
        assert len(rows) == 1
