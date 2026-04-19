"""Scheduled re-ingest — check URL sources for updates.

Periodically re-fetches URL-sourced documents, compares content,
and re-ingests if the source has changed.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReingestReport:
    """Summary of a re-ingest cycle."""

    checked: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def reingest_url_sources(
    conn: sqlite3.Connection,
    home: Path,
    workspace: str,
    workspace_path: Path,
    *,
    limit: int = 20,
) -> ReingestReport:
    """Re-fetch URL sources and re-ingest if content changed."""
    from alexandria.core.ingest import IngestError, ingest_file
    from alexandria.core.web import WebFetchError, fetch_and_save

    report = ReingestReport()

    rows = conn.execute(
        """SELECT path, content_hash FROM documents
        WHERE workspace = ? AND layer = 'raw' AND path LIKE 'raw/web/%'
        ORDER BY updated_at ASC LIMIT ?""",
        (workspace, limit),
    ).fetchall()

    for row in rows:
        raw_path = workspace_path / row["path"]
        if not raw_path.exists():
            continue

        url = _extract_source_url(raw_path)
        if not url:
            continue

        report.checked += 1

        try:
            source_path = fetch_and_save(url, workspace_path)
        except WebFetchError as exc:
            report.errors.append(f"{url}: {exc}")
            continue

        try:
            result = ingest_file(
                home=home, workspace_slug=workspace, workspace_path=workspace_path,
                source_file=source_path,
            )
            if result.committed:
                report.updated += 1
            else:
                report.unchanged += 1
        except IngestError as exc:
            report.errors.append(f"{url}: {exc}")

    return report


def _extract_source_url(raw_path: Path) -> str | None:
    """Extract the source URL from a raw file's metadata header."""
    try:
        content = raw_path.read_text(encoding="utf-8")
    except OSError:
        return None

    for line in content.split("\n")[:10]:
        match = re.match(r"- source:\s*(https?://\S+)", line)
        if match:
            return match.group(1)
    return None
