"""Tests for RSS/Atom subscription adapter."""

from pathlib import Path

import pytest

from llmwiki.core.adapters.rss import (
    RSSAdapter,
    _detect_paywall,
    _html_to_markdown,
    _parse_feed,
    _slug_from_url,
    _slugify,
    _write_subscription_file,
)

# Minimal valid Atom feed for testing
ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Blog</title>
  <link href="https://example.com"/>
  <entry>
    <id>urn:uuid:entry-1</id>
    <title>First Post</title>
    <link href="https://example.com/post-1"/>
    <author><name>Alice</name></author>
    <updated>2025-03-15T10:00:00Z</updated>
    <summary type="html">&lt;p&gt;This is the first post.&lt;/p&gt;</summary>
  </entry>
  <entry>
    <id>urn:uuid:entry-2</id>
    <title>Second Post</title>
    <link href="https://example.com/post-2"/>
    <author><name>Bob</name></author>
    <updated>2025-03-16T12:00:00Z</updated>
    <content type="html">&lt;h2&gt;Full Content&lt;/h2&gt;&lt;p&gt;Detailed article.&lt;/p&gt;</content>
  </entry>
</feed>"""

RSS_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>RSS Blog</title>
    <link>https://rss-example.com</link>
    <item>
      <guid>https://rss-example.com/post-1</guid>
      <title>RSS Post</title>
      <link>https://rss-example.com/post-1</link>
      <pubDate>Sat, 15 Mar 2025 10:00:00 GMT</pubDate>
      <description>&lt;p&gt;RSS content here.&lt;/p&gt;</description>
    </item>
  </channel>
</rss>"""


class TestParseFeed:
    def test_parse_atom(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        assert len(entries) == 2
        assert entries[0]["title"] == "First Post"
        assert entries[0]["id"] == "urn:uuid:entry-1"

    def test_parse_rss(self) -> None:
        entries = _parse_feed(RSS_FEED)
        assert len(entries) == 1
        assert entries[0]["title"] == "RSS Post"

    def test_atom_content_preferred_over_summary(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        second = entries[1]
        assert "Full Content" in second["content"]

    def test_atom_summary_fallback(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        first = entries[0]
        assert "first post" in first["content"].lower() or "first post" in first["summary"].lower()

    def test_feed_title_captured(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        assert entries[0]["feed_title"] == "Test Blog"

    def test_author_extracted(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        assert entries[0]["author"] == "Alice"

    def test_published_date(self) -> None:
        entries = _parse_feed(ATOM_FEED)
        assert "2025-03-15" in entries[0]["published"]


class TestPaywallDetection:
    def test_no_paywall(self) -> None:
        assert _detect_paywall("Normal content here.", "") is False

    def test_paid_subscribers(self) -> None:
        assert _detect_paywall("This post is for paid subscribers only.", "") is True

    def test_subscribe_to_read(self) -> None:
        assert _detect_paywall("Subscribe to read the full article.", "") is True

    def test_empty_content(self) -> None:
        assert _detect_paywall("", "") is False


class TestHtmlToMarkdown:
    def test_basic_html(self) -> None:
        result = _html_to_markdown("<p>Hello <strong>world</strong></p>")
        assert "Hello" in result
        assert "world" in result

    def test_empty(self) -> None:
        assert _html_to_markdown("") == ""

    def test_heading(self) -> None:
        result = _html_to_markdown("<h2>Title</h2><p>Body</p>")
        assert "Title" in result
        assert "Body" in result


class TestSlugify:
    def test_basic(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self) -> None:
        assert _slugify("What's New? (2025)") == "whats-new-2025"

    def test_empty(self) -> None:
        assert _slugify("") == "untitled"


class TestSlugFromUrl:
    def test_basic(self) -> None:
        assert "example" in _slug_from_url("https://www.example.com/feed")

    def test_substack(self) -> None:
        result = _slug_from_url("https://mysite.substack.com/feed")
        assert "substack" in result


class TestRSSAdapter:
    def test_sync_with_atom(self, tmp_path: Path, monkeypatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        monkeypatch.setattr(
            "llmwiki.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        adapter = RSSAdapter()
        items, result = adapter.sync(workspace, {"feed_url": "https://example.com/feed"})

        assert result.items_synced == 2
        assert len(items) == 2
        assert items[0].title == "First Post"

        # Verify files written
        subs_dir = workspace / "raw" / "subscriptions"
        assert subs_dir.exists()
        md_files = list(subs_dir.rglob("*.md"))
        assert len(md_files) == 2

    def test_sync_with_rss(self, tmp_path: Path, monkeypatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        monkeypatch.setattr(
            "llmwiki.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: RSS_FEED,
        )

        adapter = RSSAdapter()
        items, result = adapter.sync(workspace, {"feed_url": "https://rss-example.com/feed"})

        assert result.items_synced == 1
        assert items[0].title == "RSS Post"

    def test_idempotent_sync(self, tmp_path: Path, monkeypatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        monkeypatch.setattr(
            "llmwiki.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        adapter = RSSAdapter()
        # First sync
        adapter.sync(workspace, {"feed_url": "https://example.com/feed"})
        # Second sync - files already exist
        items, result = adapter.sync(workspace, {"feed_url": "https://example.com/feed"})
        # Items are still returned (dedup happens at subscription_poll level)
        assert result.items_synced == 2

    def test_validate_config(self) -> None:
        adapter = RSSAdapter()
        assert adapter.validate_config({"feed_url": "https://example.com/feed"}) == []
        assert len(adapter.validate_config({})) > 0

    def test_event_data_has_external_id(self, tmp_path: Path, monkeypatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        monkeypatch.setattr(
            "llmwiki.core.adapters.rss._fetch_feed",
            lambda url, timeout=30: ATOM_FEED,
        )

        adapter = RSSAdapter()
        items, _ = adapter.sync(workspace, {"feed_url": "https://example.com/feed"})

        assert items[0].event_data["external_id"] == "urn:uuid:entry-1"
        assert "content_hash" in items[0].event_data
        assert "content_path" in items[0].event_data
