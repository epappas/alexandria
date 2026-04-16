"""``list`` — structural browse with glob support.

Like Glob in Claude Code. Returns file paths matching a pattern within the
workspace, scoped to the raw/ and wiki/ layers.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="list",
        description=(
            "Structural browse. Glob-aware. "
            "Examples: path='*.md' (root files), path='wiki/concepts/*' (concept pages), "
            "path='raw/**' (all raw sources recursively). "
            "Returns file paths with sizes and modification times."
        ),
    )
    def list_files(
        workspace: str | None = None,
        path: str = "*",
        limit: int = 100,
    ) -> str:
        ws_path, slug = resolve(workspace)

        # Resolve glob against the workspace root
        matches = _glob_workspace(ws_path, path, limit)

        if not matches:
            return f"No files matching `{path}` in workspace `{slug}`."

        lines = [f"**{len(matches)} file(s)** matching `{path}` in `{slug}`:\n"]
        for rel_path, size, is_dir in matches:
            if is_dir:
                lines.append(f"  {rel_path}/")
            else:
                tokens_est = size // 4
                lines.append(f"  {rel_path}  ({size} bytes, ~{tokens_est} tokens)")

        if len(matches) >= limit:
            lines.append(f"\n(showing first {limit} results)")

        return "\n".join(lines)


def _glob_workspace(
    ws_path: Path, pattern: str, limit: int
) -> list[tuple[str, int, bool]]:
    """Return (relative_path, size_bytes, is_dir) tuples matching the glob."""
    results: list[tuple[str, int, bool]] = []

    # Use fnmatch for flexible patterns against all workspace files
    for entry in sorted(ws_path.rglob("*")):
        if entry.name.startswith(".") or "__pycache__" in str(entry):
            continue
        rel = str(entry.relative_to(ws_path))
        if fnmatch(rel, pattern) or fnmatch(entry.name, pattern):
            is_dir = entry.is_dir()
            size = entry.stat().st_size if not is_dir else 0
            results.append((rel, size, is_dir))
            if len(results) >= limit:
                break

    return results
