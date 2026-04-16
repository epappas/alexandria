"""``grep`` — regex / exact-match pattern search across workspace files.

The sharp tool for error codes, quoted phrases, symbol names. Uses Python's
``re`` module (not subprocess ripgrep) for portability. Phase 1 only searches
text files; binary detection defers to Phase 4.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver

TEXT_EXTENSIONS = {".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv", ".html", ".xml"}
MAX_RESULTS = 50
CONTEXT_CHARS = 120


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="grep",
        description=(
            "Regex / exact-match search across workspace files. "
            "The sharp tool for error codes, quoted phrases, symbol names. "
            "Returns matching lines with context. "
            "Use `path` to scope: 'wiki/**' for wiki only, 'raw/**' for raw only."
        ),
    )
    def grep(
        workspace: str | None = None,
        pattern: str = "",
        path: str = "**",
        ignore_case: bool = False,
        limit: int = MAX_RESULTS,
    ) -> str:
        if not pattern:
            return "error: `pattern` is required"
        ws_path, slug = resolve(workspace)

        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return f"error: invalid regex pattern: {exc}"

        hits: list[str] = []
        files_searched = 0

        target = ws_path
        # Simple path prefix scoping
        if path and path not in ("**", "*"):
            prefix = path.rstrip("*").rstrip("/")
            candidate = ws_path / prefix
            if candidate.exists() and candidate.is_dir():
                target = candidate

        for filepath in sorted(target.rglob("*")):
            if not filepath.is_file():
                continue
            if filepath.suffix not in TEXT_EXTENSIONS:
                continue
            if filepath.name.startswith(".") or "__pycache__" in str(filepath):
                continue
            files_searched += 1
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for line_no, line in enumerate(text.split("\n"), 1):
                match = compiled.search(line)
                if match:
                    rel = filepath.relative_to(ws_path)
                    snippet = line.strip()
                    if len(snippet) > CONTEXT_CHARS * 2:
                        start = max(0, match.start() - CONTEXT_CHARS)
                        end = min(len(snippet), match.end() + CONTEXT_CHARS)
                        snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(snippet) else "")
                    hits.append(f"**{rel}:{line_no}** — {snippet}")
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break

        if not hits:
            return f"No matches for `{pattern}` in `{slug}` ({files_searched} files searched)."

        header = f"**{len(hits)} match(es)** for `{pattern}` in `{slug}` ({files_searched} files searched):\n"
        return header + "\n".join(hits)
