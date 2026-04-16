"""llmwiki MCP server.

Exposes the knowledge engine's read-only primitives over stdio (primary) or
HTTP+SSE (when the daemon is running, Phase 6). Phase 1 ships stdio only.

Two binding modes per ``08_mcp_integration.md``:
- **Open mode** (``llmwiki mcp serve``): all workspaces accessible, every tool
  requires an explicit ``workspace`` argument.
- **Pinned mode** (``llmwiki mcp serve --workspace <slug>``): locked to one
  workspace; ``workspace`` defaults to the pinned slug, any other value is
  rejected with ``workspace_not_accessible``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from llmwiki.config import load_config, resolve_home
from llmwiki.core.workspace import (
    WorkspaceNotFoundError,
    get_workspace,
    list_workspaces,
    workspaces_dir,
)
from llmwiki.mcp.tools import register_all

INSTRUCTIONS = (
    "You are connected to an llmwiki knowledge engine. "
    "llmwiki accumulates the user's gathered knowledge (raw sources, compiled "
    "wiki pages, event streams, AI conversations) and exposes it through the "
    "tools below. Call `guide` first to orient yourself, then use `overview` "
    "for a quick structural snapshot, then compose `list`, `grep`, `search`, "
    "`read`, and `follow` to navigate. "
    "This is a read-only surface in Phase 1 — write tools arrive in Phase 2."
)


class WorkspaceAccessError(Exception):
    """Raised when a workspace argument fails validation in pinned mode."""


def create_server(
    *,
    pinned_workspace: str | None = None,
) -> FastMCP:
    """Build and return a configured FastMCP instance with all Phase 1 tools.

    Args:
        pinned_workspace: if given, lock the server to this workspace slug.
            Tools that pass a different workspace will be rejected.
    """
    home = resolve_home()

    mcp = FastMCP(
        "llmwiki",
        instructions=INSTRUCTIONS,
    )

    def resolve_workspace(workspace_arg: str | None) -> tuple[Path, str]:
        """Validate and resolve a workspace argument.

        Returns ``(workspace_path, slug)`` on success.
        Raises ``WorkspaceAccessError`` on bad input.
        """
        if pinned_workspace is not None:
            slug = workspace_arg or pinned_workspace
            if slug != pinned_workspace:
                raise WorkspaceAccessError(
                    f"workspace_not_accessible: this server is pinned to "
                    f"'{pinned_workspace}', got '{slug}'"
                )
        else:
            if not workspace_arg:
                raise WorkspaceAccessError(
                    "workspace argument is required in open mode — "
                    "pass the workspace slug explicitly"
                )
            slug = workspace_arg

        try:
            ws = get_workspace(home, slug)
        except WorkspaceNotFoundError as exc:
            raise WorkspaceAccessError(str(exc)) from exc

        return ws.path, slug

    register_all(mcp, resolve_workspace)
    return mcp


def run_stdio(pinned_workspace: str | None = None) -> None:
    """Start the MCP server on stdio. Blocks until the client disconnects.

    Logs to stderr only — stdout is the MCP protocol channel.
    """
    server = create_server(pinned_workspace=pinned_workspace)
    server.run(transport="stdio")
