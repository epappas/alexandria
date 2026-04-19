"""Auto-ingest pending subscription items into the wiki.

After polling (RSS, IMAP), pending items are processed through the
ingest pipeline and marked as ingested on success.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alexandria.core.ingest import IngestError, ingest_file


@dataclass
class AutoIngestReport:
    """Summary of an auto-ingest cycle."""

    ingested: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def auto_ingest_pending(
    conn: sqlite3.Connection,
    home: Path,
    workspace: str,
    workspace_path: Path,
    *,
    limit: int = 20,
) -> AutoIngestReport:
    """Process pending subscription items through the ingest pipeline.

    Only processes items from sources with auto_ingest enabled in config.
    """
    rows = conn.execute(
        """SELECT si.item_id, si.title, si.content_path, si.adapter_type, si.url
        FROM subscription_items si
        LEFT JOIN source_adapters sa ON si.source_id = sa.source_id
        WHERE si.workspace = ? AND si.status = 'pending'
          AND sa.config_json LIKE '%"auto_ingest"%'
        ORDER BY si.published_at ASC LIMIT ?""",
        (workspace, limit),
    ).fetchall()

    report = AutoIngestReport()
    for row in rows:
        item_id = row["item_id"]
        content_path = row["content_path"]

        if not content_path:
            report.skipped += 1
            continue

        source_file = workspace_path / content_path
        if not source_file.exists():
            report.skipped += 1
            continue

        topic = _topic_for_adapter(row["adapter_type"])
        try:
            result = ingest_file(
                home=home, workspace_slug=workspace, workspace_path=workspace_path,
                source_file=source_file, topic=topic,
            )
        except IngestError as exc:
            report.failed += 1
            report.errors.append(f"{row['title'][:50]}: {exc}")
            continue

        if result.committed:
            from alexandria.core.adapters.subscription_repository import mark_ingested
            mark_ingested(conn, item_id)
            report.ingested += 1
        else:
            report.skipped += 1

    return report


def _topic_for_adapter(adapter_type: str) -> str:
    """Map adapter type to a wiki topic directory."""
    return {"rss": "feeds", "imap": "newsletters"}.get(adapter_type, "subscriptions")
