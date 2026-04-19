"""Weekly self-report generator.

Per amendment I6: generates ~/.alexandria/reports/weekly.md after syncs.
Contains counts per source, error summaries, and top slowest runs.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def generate_weekly_report(conn: sqlite3.Connection, home: Path) -> Path:
    """Generate or update the weekly self-report. Returns the report path."""
    reports_dir = home / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    week_start = (now - timedelta(days=7)).isoformat()
    report_path = reports_dir / "weekly.md"

    lines = [
        "# alexandria Weekly Report",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Period: {week_start[:10]} to {now.strftime('%Y-%m-%d')}",
        "",
    ]

    # Source sync summary
    lines.append("## Source Sync Summary")
    lines.append("")
    rows = conn.execute(
        """SELECT sa.name, sa.adapter_type,
                  COUNT(sr.source_run_id) as run_count,
                  SUM(sr.items_synced) as total_synced,
                  SUM(sr.items_errored) as total_errors
           FROM source_adapters sa
           LEFT JOIN source_runs sr ON sa.source_id = sr.source_id
                AND sr.started_at >= ?
           GROUP BY sa.source_id
           ORDER BY sa.name""",
        (week_start,),
    ).fetchall()

    if rows:
        lines.append("| Source | Type | Runs | Items Synced | Errors |")
        lines.append("|--------|------|------|-------------|--------|")
        for row in rows:
            lines.append(
                f"| {row['name']} | {row['adapter_type']} | "
                f"{row['run_count']} | {row['total_synced'] or 0} | "
                f"{row['total_errors'] or 0} |"
            )
    else:
        lines.append("No sources configured.")
    lines.append("")

    # Error details
    lines.append("## Recent Errors")
    lines.append("")
    error_rows = conn.execute(
        """SELECT sa.name, sr.started_at, sr.error_message
           FROM source_runs sr
           JOIN source_adapters sa ON sr.source_id = sa.source_id
           WHERE sr.started_at >= ? AND sr.error_message IS NOT NULL
           ORDER BY sr.started_at DESC LIMIT 10""",
        (week_start,),
    ).fetchall()

    if error_rows:
        for row in error_rows:
            lines.append(f"- **{row['name']}** ({row['started_at'][:16]}): {row['error_message']}")
    else:
        lines.append("No errors this week.")
    lines.append("")

    # Top 10 slowest runs
    lines.append("## Slowest Sync Runs")
    lines.append("")
    slow_rows = conn.execute(
        """SELECT sa.name, sr.started_at, sr.ended_at, sr.items_synced
           FROM source_runs sr
           JOIN source_adapters sa ON sr.source_id = sa.source_id
           WHERE sr.started_at >= ? AND sr.ended_at IS NOT NULL
           ORDER BY (julianday(sr.ended_at) - julianday(sr.started_at)) DESC
           LIMIT 10""",
        (week_start,),
    ).fetchall()

    if slow_rows:
        for row in slow_rows:
            lines.append(
                f"- {row['name']}: {row['started_at'][:16]} "
                f"({row['items_synced']} items)"
            )
    else:
        lines.append("No completed runs this week.")
    lines.append("")

    # Event stream summary
    lines.append("## Events Ingested")
    lines.append("")
    event_rows = conn.execute(
        """SELECT source_type, event_type, COUNT(*) as cnt
           FROM events WHERE ingested_at >= ?
           GROUP BY source_type, event_type
           ORDER BY cnt DESC""",
        (week_start,),
    ).fetchall()

    if event_rows:
        for row in event_rows:
            lines.append(f"- {row['source_type']}/{row['event_type']}: {row['cnt']}")
    else:
        lines.append("No events ingested this week.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
