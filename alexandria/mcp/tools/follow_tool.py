"""``follow`` — citation walk from a wiki page's footnote to the raw source.

In Phase 1 this is a simplified version: it resolves the footnote path and
reads the raw file. The hash-anchor verification arrives in Phase 2 when
``wiki_claim_provenance`` and the verifier are in place.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from alexandria.mcp.tools import WorkspaceResolver

FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]:\s*(.+?)(?:,\s*p\.?\s*(\d+))?$", re.MULTILINE)
MAX_CONTENT = 8_000


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="follow",
        description=(
            "Follow a citation from a wiki page's footnote to the cited raw source. "
            "Give the wiki page path and the footnote number (e.g. '1' for [^1]). "
            "Returns the cited raw file's content (or the relevant page if a page "
            "hint is present). In Phase 2, this also verifies the verbatim quote "
            "anchor against the source via sha256."
        ),
    )
    def follow(
        workspace: str | None = None,
        wiki_page: str = "",
        footnote_id: str = "1",
    ) -> str:
        if not wiki_page:
            return "error: `wiki_page` is required (path relative to workspace root)"
        ws_path, slug = resolve(workspace)

        page_path = ws_path / wiki_page.lstrip("/")
        if not page_path.exists():
            return f"Wiki page not found: `{wiki_page}` in workspace `{slug}`."

        try:
            page_text = page_path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"error reading wiki page: {exc}"

        # Parse footnotes
        footnotes = {}
        for match in FOOTNOTE_RE.finditer(page_text):
            fn_id = match.group(1)
            fn_source = match.group(2).strip()
            fn_page = match.group(3)
            footnotes[fn_id] = (fn_source, fn_page)

        if footnote_id not in footnotes:
            available = ", ".join(sorted(footnotes.keys())) or "(none)"
            return (
                f"Footnote [^{footnote_id}] not found in `{wiki_page}`. "
                f"Available footnotes: {available}"
            )

        source_ref, page_hint = footnotes[footnote_id]

        # Try to resolve the source reference to a file
        source_path = _resolve_source(ws_path, page_path, source_ref)
        if source_path is None:
            return (
                f"Citation [^{footnote_id}]: `{source_ref}` — "
                f"could not resolve to a file in the workspace. "
                f"The file may have been moved or not yet ingested."
            )

        try:
            content = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"error reading source: {exc}"

        rel = source_path.relative_to(ws_path)
        header = f"**Citation [^{footnote_id}]**: `{source_ref}`\n"
        header += f"**Resolved to**: `{rel}`\n"
        if page_hint:
            header += f"**Page hint**: {page_hint}\n"
        header += "\n---\n\n"

        if len(content) > MAX_CONTENT:
            content = content[:MAX_CONTENT] + "\n\n... (truncated)"

        return header + content


def _resolve_source(ws_path: Path, wiki_page: Path, source_ref: str) -> Path | None:
    """Try to find the cited source file.

    Resolution order:
    1. As a path relative to the wiki page's directory.
    2. As a path relative to the workspace root.
    3. As a filename searched recursively under raw/.
    """
    # 1. Relative to the wiki page
    candidate = (wiki_page.parent / source_ref).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate

    # 2. Relative to workspace root
    candidate = (ws_path / source_ref.lstrip("/")).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate

    # 3. Filename search under raw/
    raw_dir = ws_path / "raw"
    if raw_dir.exists():
        name = Path(source_ref).name
        for match in raw_dir.rglob(name):
            if match.is_file():
                return match

    return None
