"""Tests for subscription poll orchestrator."""

import pytest

from alexandria.core.adapters.subscription_poll import poll_subscriptions
from alexandria.core.adapters.subscription_repository import list_subscription_items
from alexandria.core.adapters.source_repository import insert_source
from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator


# Minimal Atom feed for integration testing
ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Blog</title>
  <entry>
    <id>urn:uuid:poll-1</id>
    <title>Poll Post</title>
    <link href="https://example.com/poll-1"/>
    <updated>2025-03-15T10:00:00Z</updated>
    <summary type="html">&lt;p&gt;Poll content.&lt;/p&gt;</summary>
  </entry>
</feed>"""


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


class TestSubscriptionPoll:
    def test_poll_rss_source(self, conn, workspace_path, monkeypatch) -> None:
        # Add an RSS source
        conn.execute("BEGIN IMMEDIATE")
        insert_source(conn, "test", "rss", "test-blog", {"feed_url": "https://example.com/feed"})
        conn.execute("COMMIT")

        monkeypatch.setattr(
            "alexandria.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        report = poll_subscriptions(conn, "test", workspace_path)
        assert report.sources_polled == 1
        assert report.items_new == 1
        assert report.items_skipped == 0

        # Verify item in subscription_items
        items = list_subscription_items(conn, "test", status="pending")
        assert len(items) == 1
        assert items[0].title == "Poll Post"

    def test_poll_deduplicates(self, conn, workspace_path, monkeypatch) -> None:
        conn.execute("BEGIN IMMEDIATE")
        insert_source(conn, "test", "rss", "test-blog", {"feed_url": "https://example.com/feed"})
        conn.execute("COMMIT")

        monkeypatch.setattr(
            "alexandria.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        # First poll
        report1 = poll_subscriptions(conn, "test", workspace_path)
        assert report1.items_new == 1

        # Second poll - same content -> skipped
        report2 = poll_subscriptions(conn, "test", workspace_path)
        assert report2.items_new == 0
        assert report2.items_skipped == 1

    def test_poll_no_subscription_sources(self, conn, workspace_path) -> None:
        # Add a non-subscription source
        conn.execute("BEGIN IMMEDIATE")
        insert_source(conn, "test", "local", "docs", {"path": "/tmp"})
        conn.execute("COMMIT")

        report = poll_subscriptions(conn, "test", workspace_path)
        assert report.sources_polled == 0

    def test_poll_specific_source(self, conn, workspace_path, monkeypatch) -> None:
        conn.execute("BEGIN IMMEDIATE")
        sid = insert_source(conn, "test", "rss", "blog-a", {"feed_url": "https://a.com/feed"})
        insert_source(conn, "test", "rss", "blog-b", {"feed_url": "https://b.com/feed"})
        conn.execute("COMMIT")

        monkeypatch.setattr(
            "alexandria.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        report = poll_subscriptions(conn, "test", workspace_path, source_id=sid)
        assert report.sources_polled == 1
