"""``read`` — fetch file content from the workspace.

Single file or glob batch, with a character budget for batch reads.
Phase 1: reads from the raw filesystem. Phase 2 makes it staging-aware
so the verifier can read staged content.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver

MAX_BATCH_CHARS = 120_000
TEXT_EXTENSIONS = {".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv", ".html", ".xml"}


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:

    @mcp.tool(
        name="read",
        description=(
            "Read file content from the workspace. "
            "Accepts a single file path OR a glob pattern for batch reads:\n"
            "- path='wiki/concepts/auth.md' — read one file\n"
            "- path='wiki/**/*.md' — batch read all wiki markdown files\n"
            "- path='raw/local/*' — batch read all local raw sources\n"
            "Batch reads sample up to 120k chars across all matching files. "
            "Use single-file reads for full content."
        ),
    )
    def read(
        workspace: str | None = None,
        path: str = "",
    ) -> str:
        if not path:
            return "error: `path` is required"
        ws_path, slug = resolve(workspace)

        is_glob = "*" in path or "?" in path

        if is_glob:
            return _read_batch(ws_path, slug, path)
        return _read_single(ws_path, slug, path)


def _read_single(ws_path: Path, slug: str, path: str) -> str:
    """Read a single file's full content."""
    target = ws_path / path.lstrip("/")

    if not target.exists():
        return f"File not found: `{path}` in workspace `{slug}`."
    if not target.is_file():
        return f"`{path}` is a directory, not a file. Use `list` to browse it."

    # Security: ensure the path doesn't escape the workspace
    try:
        target.resolve().relative_to(ws_path.resolve())
    except ValueError:
        return f"error: path `{path}` escapes the workspace boundary."

    size = target.stat().st_size
    tokens_est = size // 4

    header = (
        f"**{path}** ({size} bytes, ~{tokens_est} tokens)\n"
        f"---\n\n"
    )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"error reading `{path}`: {exc}"

    return header + content


def _read_batch(ws_path: Path, slug: str, pattern: str) -> str:
    """Batch-read files matching a glob, up to the char budget."""
    matches: list[Path] = []
    for filepath in sorted(ws_path.rglob("*")):
        if not filepath.is_file():
            continue
        if filepath.name.startswith(".") or "__pycache__" in str(filepath):
            continue
        rel = str(filepath.relative_to(ws_path))
        if fnmatch(rel, pattern) or fnmatch(filepath.name, pattern):
            matches.append(filepath)

    if not matches:
        return f"No files matching `{pattern}` in workspace `{slug}`."

    parts: list[str] = []
    chars_used = 0
    files_included = 0
    files_skipped = 0

    for filepath in matches:
        if filepath.suffix not in TEXT_EXTENSIONS:
            files_skipped += 1
            continue

        remaining = MAX_BATCH_CHARS - chars_used
        if remaining <= 0:
            files_skipped += len(matches) - files_included - files_skipped
            break

        rel = str(filepath.relative_to(ws_path))
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            files_skipped += 1
            continue

        if len(content) > remaining:
            content = content[:remaining] + "\n\n... (truncated)"

        parts.append(f"### {rel}\n\n{content}")
        chars_used += len(content)
        files_included += 1

    header = f"**{files_included} file(s)** matching `{pattern}`"
    if files_skipped:
        header += f" ({files_skipped} skipped — binary or over budget)"
    header += "\n\n---\n\n"

    return header + "\n\n---\n\n".join(parts)
