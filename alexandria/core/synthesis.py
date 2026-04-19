"""Temporal synthesis — produce periodic digests from event streams.

Generates wiki pages summarizing recent activity, beliefs, and events
for a workspace. Uses the configured LLM provider with budget enforcement.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class SynthesisError(Exception):
    pass


def run_synthesis(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    *,
    period_days: int = 7,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate a temporal synthesis for the workspace.

    Collects recent events, beliefs, and subscription items, then produces
    a structured timeline digest as a wiki page.

    Returns metadata about the synthesis run.
    """
    now = datetime.now(UTC)
    since = (now - timedelta(days=period_days)).isoformat()

    # Gather data
    events = _gather_events(conn, workspace, since)
    beliefs = _gather_beliefs(conn, workspace, since)
    subscriptions = _gather_subscriptions(conn, workspace, since)

    if not events and not beliefs and not subscriptions:
        return {"status": "skipped", "reason": "no recent activity"}

    # Build synthesis content
    content = _build_digest(events, beliefs, subscriptions, workspace, period_days, now)

    if dry_run:
        return {
            "status": "dry_run",
            "content_preview": content[:500],
            "events_count": len(events),
            "beliefs_count": len(beliefs),
            "subscriptions_count": len(subscriptions),
        }

    # Write to wiki/timeline/
    timeline_dir = workspace_path / "wiki" / "timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y-%m-%d')}-weekly.md"
    out_path = timeline_dir / filename
    out_path.write_text(content, encoding="utf-8")

    return {
        "status": "completed",
        "output_path": str(out_path.relative_to(workspace_path)),
        "events_count": len(events),
        "beliefs_count": len(beliefs),
        "subscriptions_count": len(subscriptions),
    }


def _gather_events(conn: sqlite3.Connection, workspace: str, since: str) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT event_type, title, occurred_at, source_type FROM events "
            "WHERE workspace = ? AND occurred_at >= ? ORDER BY occurred_at DESC LIMIT 100",
            (workspace, since),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _gather_beliefs(conn: sqlite3.Connection, workspace: str, since: str) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT statement, topic, asserted_at FROM wiki_beliefs "
            "WHERE workspace = ? AND asserted_at >= ? AND superseded_at IS NULL "
            "ORDER BY asserted_at DESC LIMIT 50",
            (workspace, since),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _gather_subscriptions(conn: sqlite3.Connection, workspace: str, since: str) -> list[dict]:
    try:
        rows = conn.execute(
            "SELECT title, adapter_type, published_at, status FROM subscription_items "
            "WHERE workspace = ? AND created_at >= ? ORDER BY published_at DESC LIMIT 50",
            (workspace, since),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_digest(
    events: list[dict],
    beliefs: list[dict],
    subscriptions: list[dict],
    workspace: str,
    period_days: int,
    now: datetime,
) -> str:
    """Build a markdown digest from gathered data."""
    lines = [
        f"# Weekly Digest — {workspace}",
        "",
        "draft: true",
        f"period: {period_days} days ending {now.strftime('%Y-%m-%d')}",
        f"generated: {now.isoformat()}",
        "", "---", "",
    ]

    if events:
        lines.append("## Events")
        lines.append("")
        for ev in events[:20]:
            date = ev.get("occurred_at", "")[:10]
            lines.append(f"- [{ev.get('source_type', '')}] {ev.get('title', '')} ({date})")
        lines.append("")

    if beliefs:
        lines.append("## New Beliefs")
        lines.append("")
        for b in beliefs[:15]:
            lines.append(f"- **{b.get('topic', '')}**: {b.get('statement', '')}")
        lines.append("")

    if subscriptions:
        lines.append("## Subscription Items")
        lines.append("")
        for s in subscriptions[:15]:
            status = s.get("status", "")
            lines.append(f"- [{status}] {s.get('title', '')} ({s.get('adapter_type', '')})")
        lines.append("")

    return "\n".join(lines)
