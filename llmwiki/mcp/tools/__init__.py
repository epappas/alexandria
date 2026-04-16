"""MCP tool registry.

Each tool is a module in this package with a ``register(mcp, resolve_workspace)``
function that binds the tool to the FastMCP instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from collections.abc import Callable
    from pathlib import Path

    WorkspaceResolver = Callable[[str | None], tuple[Path, str]]


def register_all(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:
    """Register all implemented MCP tools on the given FastMCP instance."""
    from llmwiki.mcp.tools import (
        guide_tool,
        overview_tool,
        list_tool,
        grep_tool,
        search_tool,
        read_tool,
        follow_tool,
        history_tool,
        why_tool,
        events_tool,
        timeline_tool,
        git_tool,
        sources_tool,
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
