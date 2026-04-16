"""``overview`` — cold-start silhouette (llm-architect recommendation #1).

Returns in one call: directory tree (depth 2) + last 20 wiki page titles +
raw source count + token estimates. Collapses 3-8 wasted exploration turns
into one call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="overview",
        description=(
            "Cold-start silhouette. One call returns: directory tree (depth 2), "
            "last 20 wiki page titles, raw source count, and token estimates. "
            "Collapses 3-8 exploration turns into one call."
        ),
    )
    def overview(workspace: str | None = None) -> str:
        ws_path, slug = resolve(workspace)
        parts: list[str] = []

        parts.append(f"# Workspace: {slug}\n")

        # Directory tree depth 2
        parts.append("## Directory tree (depth 2)\n```")
        parts.extend(_tree(ws_path, max_depth=2))
        parts.append("```\n")

        # Wiki pages (last 20 by mtime)
        wiki_dir = ws_path / "wiki"
        if wiki_dir.exists():
            wiki_files = sorted(
                (f for f in wiki_dir.rglob("*.md") if f.is_file()),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:20]
            parts.append("## Wiki pages (recent 20)\n")
            for f in wiki_files:
                rel = f.relative_to(ws_path)
                size = f.stat().st_size
                tokens_est = size // 4
                parts.append(f"- `{rel}` (~{tokens_est} tokens)")
        else:
            parts.append("## Wiki pages\nNo wiki/ directory yet.\n")

        # Raw source count
        raw_dir = ws_path / "raw"
        if raw_dir.exists():
            raw_count = sum(1 for f in raw_dir.rglob("*") if f.is_file() and f.name != ".gitkeep")
            parts.append(f"\n## Raw sources: {raw_count}")
        else:
            parts.append("\n## Raw sources: 0")

        # Total token estimate
        total_bytes = sum(
            f.stat().st_size
            for f in ws_path.rglob("*")
            if f.is_file() and f.suffix in (".md", ".txt", ".json", ".toml")
        )
        parts.append(f"\n## Total text estimate: ~{total_bytes // 4} tokens")

        return "\n".join(parts)


def _tree(root: Path, max_depth: int, _prefix: str = "", _depth: int = 0) -> list[str]:
    """Produce a simple tree listing like the ``tree`` command."""
    lines: list[str] = []
    if _depth == 0:
        lines.append(root.name + "/")
    if _depth >= max_depth:
        return lines
    try:
        entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name))
    except PermissionError:
        return lines
    visible = [e for e in entries if not e.name.startswith(".") and e.name != "__pycache__"]
    for i, entry in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└── " if is_last else "├── "
        if entry.is_dir():
            lines.append(f"{_prefix}{connector}{entry.name}/")
            extension = "    " if is_last else "│   "
            lines.extend(_tree(entry, max_depth, _prefix + extension, _depth + 1))
        else:
            lines.append(f"{_prefix}{connector}{entry.name}")
    return lines
