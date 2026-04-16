"""``why`` MCP tool — belief explainability.

Read-only. Returns current beliefs + history + verbatim source quotes.
No LLM calls — pure SQL over wiki_beliefs + wiki_beliefs_fts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from llmwiki.config import resolve_home
from llmwiki.core.beliefs.repository import BeliefQuery, get_belief, query_beliefs
from llmwiki.db.connection import connect, db_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:

    @mcp.tool(
        name="why",
        description=(
            "Belief explainability. Returns current beliefs matching the query "
            "plus their supersession history and citation provenance. "
            "Read-only. No LLM calls — pure SQL + FTS5 lookup. "
            "Query can be a topic name, subject, belief_id, or free text."
        ),
    )
    def why(
        query: str,
        workspace: str | None = None,
        include_history: bool = True,
    ) -> str:
        ws_path, slug = resolve(workspace)
        home = resolve_home()

        if not db_path(home).exists():
            return "No database. Run `llmwiki init` first."

        with connect(db_path(home)) as conn:
            # Direct belief_id lookup
            direct = get_belief(conn, query)
            if direct:
                beliefs = [direct]
            else:
                bq = BeliefQuery(
                    workspace=slug,
                    query=query,
                    current_only=not include_history,
                )
                beliefs = query_beliefs(conn, bq)

            # Build history chain
            history = []
            if include_history:
                for b in beliefs:
                    cur = conn.execute(
                        "SELECT * FROM wiki_beliefs WHERE superseded_by_belief_id = ?",
                        (b.belief_id,),
                    )
                    for row in cur.fetchall():
                        from llmwiki.core.beliefs.repository import _row_to_belief
                        history.append(_row_to_belief(row))

        if not beliefs and not history:
            return f"No beliefs found for `{query}` in workspace `{slug}`."

        current = [b for b in beliefs if b.is_current]
        superseded = [b for b in beliefs if not b.is_current] + history

        parts = [f'## Beliefs matching "{query}"\n']

        if current:
            parts.append("### Current beliefs\n")
            for b in current:
                parts.append(f"**{b.statement}**")
                parts.append(f"  topic: {b.topic} | page: {b.wiki_document_path}")
                if b.footnote_ids:
                    parts.append(f"  citations: {', '.join(f'[^{f}]' for f in b.footnote_ids)}")
                parts.append(f"  asserted: {b.asserted_at[:10]}")
                if b.subject:
                    parts.append(f"  structured: {b.subject} {b.predicate} {b.object}")
                parts.append("")

        if superseded:
            parts.append("### History (superseded)\n")
            for b in superseded:
                parts.append(f"~~{b.statement}~~")
                parts.append(f"  superseded: {b.superseded_at[:10] if b.superseded_at else 'unknown'} — {b.supersession_reason}")
                parts.append(f"  was asserted: {b.asserted_at[:10]}")
                parts.append("")

        return "\n".join(parts)
