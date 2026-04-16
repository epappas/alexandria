"""MCP tool: events — query the event stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:
    @mcp.tool()
    def events(
        workspace: str | None = None,
        source_type: str | None = None,
        event_type: str | None = None,
        query: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> str:
        """Query the event stream with optional filters and FTS search.

        Events come from source adapters (git commits, GitHub issues/PRs,
        file syncs, etc.). Use ``source_type`` to filter by origin, ``query``
        for full-text search, ``since``/``until`` for date range.
        """
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.core.adapters.events import EventQuery, query_events
        import json

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            eq = EventQuery(
                workspace=slug,
                source_type=source_type,
                event_type=event_type,
                query=query,
                since=since,
                until=until,
                limit=limit,
            )
            results = query_events(conn, eq)

        if not results:
            return f"No events found in {slug} matching the query."

        lines = [f"Found {len(results)} event(s) in {slug}:\n"]
        for ev in results:
            lines.append(f"- [{ev.event_type}] {ev.title}")
            lines.append(f"  source: {ev.source_type} | {ev.occurred_at[:10]}")
            if ev.author:
                lines.append(f"  author: {ev.author}")
            if ev.url:
                lines.append(f"  url: {ev.url}")
            if ev.body:
                lines.append(f"  {ev.body[:200]}")
            lines.append("")

        return "\n".join(lines)
