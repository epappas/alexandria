"""Subscription poll orchestrator.

Runs RSS and IMAP adapters, deduplicates items, and inserts into
subscription_items table. Coordinates with the event stream.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alexandria.core.adapters.events import insert_event
from alexandria.core.adapters.source_repository import (
    SourceConfig,
    complete_source_run,
    create_source_run,
    list_sources,
)
from alexandria.core.adapters.subscription_repository import (
    insert_subscription_item,
    is_duplicate,
)


@dataclass
class PollReport:
    """Summary of a poll cycle."""

    sources_polled: int = 0
    items_new: int = 0
    items_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def poll_subscriptions(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    source_id: str | None = None,
    secret_resolver: Any = None,
) -> PollReport:
    """Poll all subscription sources (RSS + IMAP) or a specific one."""
    report = PollReport()

    sources = list_sources(conn, workspace, enabled_only=True)
    if source_id:
        sources = [s for s in sources if s.source_id == source_id]

    # Filter to subscription-type adapters
    sub_types = ("rss", "imap")
    sources = [s for s in sources if s.adapter_type in sub_types]

    for src in sources:
        report.sources_polled += 1
        _poll_one(conn, src, workspace, workspace_path, report, secret_resolver)

    return report


def _poll_one(
    conn: sqlite3.Connection,
    src: SourceConfig,
    workspace: str,
    workspace_path: Path,
    report: PollReport,
    secret_resolver: Any = None,
) -> None:
    """Poll a single subscription source."""
    from alexandria.core.adapters.imap_newsletter import IMAPNewsletterAdapter
    from alexandria.core.adapters.rss import RSSAdapter

    adapter_map = {
        "rss": RSSAdapter,
        "imap": IMAPNewsletterAdapter,
    }
    adapter_cls = adapter_map.get(src.adapter_type)
    if adapter_cls is None:
        report.errors.append(f"unknown subscription adapter: {src.adapter_type}")
        return

    # Resolve vault references in config (e.g., password_ref -> password)
    config = dict(src.config_json)
    if secret_resolver and "password_ref" in config:
        config["password"] = secret_resolver.resolve(config["password_ref"])

    # Create source run tracking
    conn.execute("BEGIN IMMEDIATE")
    try:
        srun_id = create_source_run(conn, src.source_id, triggered_by="cli:poll")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    adapter = adapter_cls()
    try:
        items, sync_result = adapter.sync(workspace_path, config)
    except Exception as exc:
        report.errors.append(f"{src.name}: {exc}")
        conn.execute("BEGIN IMMEDIATE")
        try:
            complete_source_run(conn, srun_id, 0, 1, str(exc))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
        return

    # Insert subscription items with deduplication
    new_count = 0
    skip_count = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for item in items:
            data = item.event_data
            ext_id = data.get("external_id")
            c_hash = data.get("content_hash", "")

            if is_duplicate(conn, workspace, ext_id, c_hash):
                skip_count += 1
                continue

            insert_subscription_item(
                conn,
                workspace=workspace,
                source_id=src.source_id,
                adapter_type=src.adapter_type,
                title=item.title,
                content_path=data.get("content_path", ""),
                content_hash=c_hash,
                external_id=ext_id,
                author=item.author,
                url=item.url,
                published_at=item.occurred_at,
                excerpt=item.body,
                metadata={
                    k: v for k, v in data.items()
                    if k not in ("external_id", "content_hash", "content_path")
                },
            )
            insert_event(conn, workspace, src.source_id, item)
            new_count += 1

        complete_source_run(
            conn, srun_id, sync_result.items_synced, sync_result.items_errored,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    report.items_new += new_count
    report.items_skipped += skip_count
