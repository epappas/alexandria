"""MCP tool: sources — list configured source adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    @mcp.tool()
    def sources(
        workspace: str | None = None,
    ) -> str:
        """List configured source adapters with their status.

        Shows source name, type, enabled status, and last sync info.
        Read-only — use the CLI to add/remove sources.
        """
        from alexandria.config import resolve_home
        from alexandria.core.adapters.source_repository import list_source_runs, list_sources
        from alexandria.db.connection import connect, db_path

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            srcs = list_sources(conn, slug)
            if not srcs:
                return f"No sources configured in workspace {slug}."

            lines = [f"Sources in {slug}:\n"]
            for src in srcs:
                status = "enabled" if src.enabled else "disabled"
                lines.append(f"  {src.name} ({src.adapter_type}) [{status}]")
                lines.append(f"    id: {src.source_id}")

                runs = list_source_runs(conn, src.source_id, limit=1)
                if runs:
                    last = runs[0]
                    lines.append(
                        f"    last sync: {last.started_at[:16]} "
                        f"({last.status}, {last.items_synced} items)"
                    )
                else:
                    lines.append("    last sync: never")
                lines.append("")

        return "\n".join(lines)
