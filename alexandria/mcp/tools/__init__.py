"""MCP tool registry.

Each tool is a module in this package with a ``register(mcp, resolve_workspace)``
function that binds the tool to the FastMCP instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mcp.server.fastmcp import FastMCP

    WorkspaceResolver = Callable[[str | None], tuple[Path, str]]


def register_all(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    """Register all implemented MCP tools on the given FastMCP instance."""
    from alexandria.mcp.tools import (
        events_tool,
        follow_tool,
        git_tool,
        grep_tool,
        guide_tool,
        history_tool,
        list_tool,
        overview_tool,
        read_tool,
        search_tool,
        sources_tool,
        subscriptions_tool,
        timeline_tool,
        why_tool,
        write_tool,
    )

    guide_tool.register(mcp, resolve)
    overview_tool.register(mcp, resolve)
    list_tool.register(mcp, resolve)
    grep_tool.register(mcp, resolve)
    search_tool.register(mcp, resolve)
    read_tool.register(mcp, resolve)
    follow_tool.register(mcp, resolve)
    history_tool.register(mcp, resolve)
    why_tool.register(mcp, resolve)
    events_tool.register(mcp, resolve)
    timeline_tool.register(mcp, resolve)
    git_tool.register(mcp, resolve)
    sources_tool.register(mcp, resolve)
    subscriptions_tool.register(mcp, resolve)
    write_tool.register(mcp, resolve)
