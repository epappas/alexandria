"""MCP resources — read-only content via URI scheme.

Registers alexandria:// resources so MCP clients can read
wiki content, beliefs, and stats via resource URIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alexandria.config import resolve_home
from alexandria.db.connection import connect, db_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register_resources(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    """Register MCP resources for Alexandria content."""

    @mcp.resource("alexandria://stats")
    def stats_resource() -> str:
        """Workspace statistics: document count, belief count, topics, runs."""
        from alexandria.core.self_knowledge import gather_self_knowledge

        home = resolve_home()
        if not db_path(home).exists():
            return "No database. Run alexandria init."

        # Use the first available workspace
        ws_path, slug = _resolve_default(resolve)
        with connect(db_path(home)) as conn:
            return gather_self_knowledge(conn, slug)

    @mcp.resource("alexandria://index")
    def index_resource() -> str:
        """Wiki table of contents — all wiki pages listed by topic."""
        home = resolve_home()
        if not db_path(home).exists():
            return "No database."

        ws_path, slug = _resolve_default(resolve)
        with connect(db_path(home)) as conn:
            rows = conn.execute(
                "SELECT path, title FROM documents WHERE workspace = ? AND layer = 'wiki' ORDER BY path",
                (slug,),
            ).fetchall()

        if not rows:
            return "No wiki pages."

        lines = [f"# Wiki Index ({len(rows)} pages)\n"]
        current_topic = ""
        for r in rows:
            parts = r["path"].split("/")
            topic = parts[1] if len(parts) > 2 else "root"
            if topic != current_topic:
                current_topic = topic
                lines.append(f"\n## {topic}\n")
            lines.append(f"- [{r['title'] or r['path']}]({r['path']})")
        return "\n".join(lines)


def _resolve_default(resolve: WorkspaceResolver) -> tuple:
    """Resolve workspace, trying pinned first, then 'global'."""
    try:
        return resolve(None)
    except Exception:
        return resolve("global")
