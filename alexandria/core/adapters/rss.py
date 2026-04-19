"""RSS/Atom subscription adapter.

Parses RSS 2.0 and Atom 1.0 feeds via feedparser, extracts content,
converts HTML to markdown, and stores items in raw/subscriptions/.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from alexandria.core.adapters.base import AdapterKind, FetchedItem, SyncResult


class RSSAdapterError(Exception):
    pass


# Feed type detection patterns
_SUBSTACK_RE = re.compile(r"https?://\w+\.substack\.com")
_YOUTUBE_RE = re.compile(r"youtube\.com/feeds/videos")


class RSSAdapter:
    """Fetch and parse RSS/Atom feeds into subscription items."""

    kind = AdapterKind.LOCAL  # reuse local for adapter_type column compat

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        feed_url = config["feed_url"]
        result = SyncResult()

        raw = _fetch_feed(feed_url)
        entries = _parse_feed(raw)

        subs_dir = workspace_path / "raw" / "subscriptions" / _slug_from_url(feed_url)
        subs_dir.mkdir(parents=True, exist_ok=True)

        items: list[FetchedItem] = []
        for entry in entries:
            content = entry.get("content") or entry.get("summary") or ""
            content_md = _html_to_markdown(content)
            content_hash = hashlib.sha256(content_md.encode("utf-8")).hexdigest()

            # Build filename from date + title slug
            pub_date = entry.get("published") or ""
            date_prefix = pub_date[:10] if pub_date else "undated"
            title_slug = _slugify(entry.get("title", "untitled"))[:60]
            filename = f"{date_prefix}-{title_slug}.md"

            file_path = subs_dir / filename
            if not file_path.exists():
                _write_subscription_file(file_path, entry, content_md)

            items.append(FetchedItem(
                source_type="rss",
                event_type="subscription_item",
                title=entry.get("title", ""),
                body=content_md[:500] if content_md else None,
                url=entry.get("link"),
                author=entry.get("author"),
                occurred_at=pub_date or datetime.now(UTC).isoformat(),
                event_data={
                    "external_id": entry.get("id") or entry.get("link", ""),
                    "content_hash": content_hash,
                    "content_path": str(file_path.relative_to(workspace_path)),
                    "feed_url": feed_url,
                    "feed_title": entry.get("feed_title", ""),
                    "paywalled": entry.get("paywalled", False),
                    "tags": entry.get("tags", []),
                },
            ))
            result.items_synced += 1

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "feed_url" not in config:
            errors.append("'feed_url' is required for rss adapter")
        return errors


def _validate_feed_url(url: str) -> None:
    """Reject URLs that target private/internal networks (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RSSAdapterError(f"only http/https feed URLs allowed, got: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise RSSAdapterError("feed URL has no hostname")
    try:
        resolved = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise RSSAdapterError(f"cannot resolve hostname {hostname}: {exc}") from exc
    for _, _, _, _, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise RSSAdapterError(
                f"feed URL resolves to private/internal address {ip} — blocked for SSRF protection"
            )


def _fetch_feed(url: str, timeout: int = 30) -> str:
    """Fetch raw feed XML/text from URL."""
    _validate_feed_url(url)
    headers = {
        "User-Agent": "alexandria/1.0 (feed reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RSSAdapterError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise RSSAdapterError(f"network error fetching {url}: {exc.reason}") from exc


def _parse_feed(raw_xml: str) -> list[dict[str, Any]]:
    """Parse feed XML into a list of entry dicts."""
    import feedparser
    feed = feedparser.parse(raw_xml)

    feed_title = feed.feed.get("title", "")
    entries: list[dict[str, Any]] = []

    for entry in feed.entries:
        # Extract best available content
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary or ""

        # Published date
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                published = dt.isoformat()
            except (ValueError, TypeError):
                published = getattr(entry, "published", "")
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                dt = datetime(*entry.updated_parsed[:6], tzinfo=UTC)
                published = dt.isoformat()
            except (ValueError, TypeError):
                published = getattr(entry, "updated", "")

        # Tags
        tags: list[str] = []
        if hasattr(entry, "tags"):
            tags = [t.get("term", "") for t in entry.tags if t.get("term")]

        # Detect paywall markers
        paywalled = _detect_paywall(content, getattr(entry, "link", ""))

        entries.append({
            "id": getattr(entry, "id", "") or getattr(entry, "link", ""),
            "title": getattr(entry, "title", "Untitled"),
            "link": getattr(entry, "link", ""),
            "author": getattr(entry, "author", None),
            "published": published,
            "content": content,
            "summary": getattr(entry, "summary", ""),
            "tags": tags,
            "feed_title": feed_title,
            "paywalled": paywalled,
        })

    return entries


def _detect_paywall(content: str, url: str) -> bool:
    """Detect common paywall markers in content or URL."""
    if not content:
        return False
    lower = content.lower()
    markers = [
        "this post is for paid subscribers",
        "subscribe to read",
        "become a member to read",
        "this content is for subscribers only",
        "unlock this post",
    ]
    return any(m in lower for m in markers)


_DANGEROUS_URI_RE = re.compile(
    r"\[([^\]]*)\]\((javascript|data|vbscript):[^)]*\)", re.IGNORECASE
)


def _html_to_markdown(html_content: str) -> str:
    """Convert HTML to markdown. Falls back to stripped text."""
    if not html_content:
        return ""
    try:
        from markdownify import markdownify
        md = markdownify(
            html_content, heading_style="ATX",
            strip=["script", "style", "iframe", "object", "embed", "form", "input"],
        ).strip()
    except ImportError:
        clean = re.sub(r"<[^>]+>", "", html_content)
        md = html.unescape(clean).strip()
    # Strip dangerous URI schemes from markdown links
    md = _DANGEROUS_URI_RE.sub(r"\1", md)
    return md


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug or "untitled"


def _slug_from_url(url: str) -> str:
    """Derive a directory slug from a feed URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or "unknown"
    host = host.replace("www.", "")
    return re.sub(r"[^a-z0-9-]", "-", host.lower()).strip("-")[:40]


def _write_subscription_file(
    path: Path, entry: dict[str, Any], content_md: str
) -> None:
    """Write a subscription item as a markdown file with frontmatter."""
    lines = [
        f"# {entry.get('title', 'Untitled')}",
        "",
        f"- source: {entry.get('link', '')}",
        f"- author: {entry.get('author', '')}",
        f"- published: {entry.get('published', '')}",
        f"- feed: {entry.get('feed_title', '')}",
    ]
    if entry.get("tags"):
        lines.append(f"- tags: {', '.join(entry['tags'])}")
    if entry.get("paywalled"):
        lines.append("- paywalled: true")
    lines.extend(["", "---", "", content_md])

    path.write_text("\n".join(lines), encoding="utf-8")
