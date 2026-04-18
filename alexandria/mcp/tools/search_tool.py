"""``search`` — hybrid search with BM25 + recency + belief support.

The broad tool for "pages about concept X". Not the retriever — one
primitive among several that the agent composes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alexandria.config import resolve_home
from alexandria.core.search import hybrid_search
from alexandria.db.connection import connect, db_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from alexandria.mcp.tools import WorkspaceResolver


MAX_RESULTS = 20
SNIPPET_LEN = 200


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="search",
        description=(
            "Hybrid search (BM25 + recency + belief support). "
            "The broad tool for 'pages about X'. "
            "Searches both raw/ and wiki/ layers by default. "
            "Use `path_prefix` to scope: '/wiki/' for wiki only, '/raw/' for raw. "
            "Returns matching documents ranked by composite score."
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
            return f"No database found at {home}. Run `alexandria init` first."

        with connect(db_path(home)) as conn:
            hits = hybrid_search(conn, slug, query, limit=limit)

        if not hits:
            return f"No results for `{query}` in workspace `{slug}`."

        # Filter by path_prefix if given
        if path_prefix:
            hits = [h for h in hits if h.path.startswith(path_prefix.lstrip("/"))]

        lines = [f"**{len(hits)} result(s)** for `{query}` in `{slug}`:\n"]
        for hit in hits:
            snippet = _extract_snippet(hit.content, query)
            score_detail = f"score={hit.score:.2f}"
            if hit.belief_count > 0:
                score_detail += f", {hit.belief_count} belief(s)"
            lines.append(f"**{hit.path}** — {hit.title} ({score_detail})")
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
