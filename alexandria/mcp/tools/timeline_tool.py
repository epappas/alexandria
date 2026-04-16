"""MCP tool: timeline — temporal digest of events."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:
    @mcp.tool()
    def timeline(
        workspace: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
    ) -> str:
        """Temporal digest of events grouped by date.

        Returns a time-based view of all events, useful for questions like
        "what happened last week" or "show recent activity".
        """
        from collections import defaultdict
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.core.adapters.events import EventQuery, query_events

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            eq = EventQuery(
                workspace=slug, since=since, until=until, limit=limit
            )
            results = query_events(conn, eq)

        if not results:
            return f"No events in {slug} for the requested period."

        # Group by date
        by_date: dict[str, list] = defaultdict(list)
        for ev in results:
            date = ev.occurred_at[:10] if ev.occurred_at else "unknown"
            by_date[date].append(ev)

        lines = [f"Timeline for {slug} ({len(results)} events):\n"]
        for date in sorted(by_date.keys(), reverse=True):
            lines.append(f"## {date}")
            for ev in by_date[date]:
                prefix = f"[{ev.source_type}/{ev.event_type}]"
                author_str = f" by {ev.author}" if ev.author else ""
                lines.append(f"  {prefix} {ev.title}{author_str}")
            lines.append("")

        return "\n".join(lines)
