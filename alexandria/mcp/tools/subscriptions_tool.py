"""MCP tool: subscriptions — read-only listing of subscription items."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    @mcp.tool()
    def subscriptions(
        workspace: str | None = None,
        status: str | None = "pending",
        adapter: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> str:
        """List subscription items (RSS feeds, newsletters).

        Shows pending items by default. Use ``status`` to filter by
        pending/ingested/dismissed. Returns titles, excerpts, and paths
        for use with the ``read`` tool. No credentials are exposed.
        """
        from alexandria.config import resolve_home
        from alexandria.core.adapters.subscription_repository import list_subscription_items
        from alexandria.db.connection import connect, db_path

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            items = list_subscription_items(
                conn, slug, status=status, adapter_type=adapter, since=since, limit=limit,
            )

        if not items:
            return f"No {status or ''} subscription items in {slug}."

        lines = [f"Found {len(items)} subscription item(s) in {slug}:\n"]
        for item in items:
            lines.append(f"- **{item.title}**")
            lines.append(f"  id: {item.item_id} | {item.adapter_type} | {item.status}")
            if item.author:
                lines.append(f"  author: {item.author}")
            if item.published_at:
                lines.append(f"  published: {item.published_at[:10]}")
            if item.url:
                lines.append(f"  url: {item.url}")
            lines.append(f"  content: {item.content_path}")
            if item.excerpt:
                lines.append(f"  {item.excerpt[:200]}")
            lines.append("")

        return "\n".join(lines)
