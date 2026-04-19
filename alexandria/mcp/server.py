"""alexandria MCP server.

Exposes the knowledge engine's read-only primitives over stdio (primary) or
HTTP+SSE (when the daemon is running, Phase 6). Phase 1 ships stdio only.

Two binding modes per ``08_mcp_integration.md``:
- **Open mode** (``alexandria mcp serve``): all workspaces accessible, every tool
  requires an explicit ``workspace`` argument.
- **Pinned mode** (``alexandria mcp serve --workspace <slug>``): locked to one
  workspace; ``workspace`` defaults to the pinned slug, any other value is
  rejected with ``workspace_not_accessible``.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from alexandria.config import resolve_home
from alexandria.core.workspace import (
    WorkspaceNotFoundError,
    get_workspace,
)
from alexandria.mcp.tools import register_all

INSTRUCTIONS = (
    "You are connected to Alexandria, a local-first knowledge engine. "
    "Alexandria accumulates gathered knowledge (raw sources, compiled "
    "wiki pages, beliefs, AI conversations) and exposes it through the "
    "tools below.\n\n"
    "Navigation: call `guide` to orient, `overview` for a structural snapshot, "
    "then compose `search`, `grep`, `read`, `follow`, and `beliefs` to find information.\n\n"
    "Write: use `ingest` to add files, directories, URLs, git repos, or conversations. "
    "Use `belief_add` and `belief_supersede` to manage structured claims. "
    "Use `query` for LLM-powered answers grounded in the knowledge base."
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
        "alexandria",
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

    from alexandria.mcp.resources import register_resources
    register_resources(mcp, resolve_workspace)

    return mcp


def run_stdio(pinned_workspace: str | None = None) -> None:
    """Start the MCP server on stdio. Blocks until the client disconnects.

    Logs to stderr only — stdout is the MCP protocol channel.
    """
    # The MCP server is a separate process — clear CLAUDECODE so the
    # LLM provider detection allows using the Claude Code SDK.
    os.environ.pop("CLAUDECODE", None)
    server = create_server(pinned_workspace=pinned_workspace)
    server.run(transport="stdio")


def run_http(
    pinned_workspace: str | None = None,
    host: str = "127.0.0.1",
    port: int = 7219,
) -> None:
    """Start the MCP server over HTTP+SSE with web dashboard."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import FileResponse
    from starlette.routing import Route

    from alexandria.mcp.api import (
        beliefs_handler,
        documents_handler,
        search_handler,
        stats_handler,
    )

    os.environ.pop("CLAUDECODE", None)
    server = create_server(pinned_workspace=pinned_workspace)

    static_dir = Path(__file__).parent / "static"

    async def dashboard(request: object) -> FileResponse:
        return FileResponse(static_dir / "index.html")

    # Build combined app: dashboard + API + MCP SSE
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # noqa: ANN001
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'"
            )
            return response

    mcp_app = server.sse_app()
    routes = [
        Route("/", dashboard),
        Route("/api/stats", stats_handler),
        Route("/api/search", search_handler),
        Route("/api/beliefs", beliefs_handler),
        Route("/api/documents", documents_handler),
    ]
    app = Starlette(
        routes=routes,
        middleware=[Middleware(SecurityHeadersMiddleware)],
    )
    app.mount("/mcp", mcp_app)

    uvicorn.run(app, host=host, port=port)
