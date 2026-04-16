"""``search`` — FTS5 keyword search with ranking + path/tag scoping.

The broad tool for "pages about concept X". Not the retriever — one
primitive among several that the agent composes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from llmwiki.config import resolve_home
from llmwiki.db.connection import connect, db_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver


MAX_RESULTS = 20
SNIPPET_LEN = 200


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="search",
        description=(
            "FTS5 keyword search with ranking. The broad tool for 'pages about X'. "
            "Searches both raw/ and wiki/ layers by default. "
            "Use `path_prefix` to scope: '/wiki/' for wiki only, '/raw/' for raw. "
            "Returns matching documents ranked by relevance."
        ),
    )
    def search(
        query: str,
        workspace: str | None = None,
        path_prefix: str | None = None,
        limit: int = MAX_RESULTS,
    ) -> str:
        if not query.strip():
            return "error: `query` is required"
        ws_path, slug = resolve(workspace)
        home = resolve_home()

        if not db_path(home).exists():
            return f"No database found at {home}. Run `llmwiki init` first."

        with connect(db_path(home)) as conn:
            # Build query — FTS5 MATCH with optional path filter
            if path_prefix:
                sql = (
                    "SELECT d.id, d.path, d.filename, d.title, d.layer, d.content, "
                    "  rank "
                    "FROM documents_fts f "
                    "JOIN documents d ON d.rowid = f.rowid "
                    "WHERE f.documents_fts MATCH ? "
                    "  AND d.workspace = ? "
                    "  AND d.path LIKE ? "
                    "ORDER BY rank "
                    "LIMIT ?"
                )
                params = (query, slug, path_prefix + "%", limit)
            else:
                sql = (
                    "SELECT d.id, d.path, d.filename, d.title, d.layer, d.content, "
                    "  rank "
                    "FROM documents_fts f "
                    "JOIN documents d ON d.rowid = f.rowid "
                    "WHERE f.documents_fts MATCH ? "
                    "  AND d.workspace = ? "
                    "ORDER BY rank "
                    "LIMIT ?"
                )
                params = (query, slug, limit)

            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
            except Exception as exc:
                return f"Search error: {exc}"

        if not rows:
            return f"No results for `{query}` in workspace `{slug}`."

        lines = [f"**{len(rows)} result(s)** for `{query}` in `{slug}`:\n"]
        for row in rows:
            filepath = f"{row['path']}{row['filename']}"
            title = row["title"] or row["filename"]
            content = row["content"] or ""
            snippet = _extract_snippet(content, query)
            lines.append(f"**{filepath}** — {title}")
            if snippet:
                lines.append(f"```\n{snippet}\n```")
            lines.append("")

        return "\n".join(lines)


def _extract_snippet(content: str, query: str) -> str:
    """Extract a snippet around the first occurrence of the query terms."""
    if not content:
        return ""
    lower = content.lower()
    first_term = query.split()[0].lower() if query.split() else ""
    idx = lower.find(first_term) if first_term else -1
    if idx < 0:
        return content[:SNIPPET_LEN].strip()
    start = max(0, idx - SNIPPET_LEN // 2)
    end = min(len(content), idx + SNIPPET_LEN)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet
