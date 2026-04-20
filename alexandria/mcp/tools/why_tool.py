"""``why`` MCP tool — belief explainability.

Read-only. Returns current beliefs + history + verbatim source quotes.
No LLM calls — pure SQL over wiki_beliefs + wiki_beliefs_fts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alexandria.config import resolve_home
from alexandria.core.beliefs.repository import BeliefQuery, get_belief, query_beliefs
from alexandria.db.connection import connect, db_path

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:

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
            return "No database. Run `alexandria init` first."

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
                        from alexandria.core.beliefs.repository import _row_to_belief
                        history.append(_row_to_belief(row))

            # Get source_kind for beliefs while connection is open
            kind_map: dict[str, str] = {}
            try:
                sk_rows = conn.execute(
                    "SELECT belief_id, source_kind FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NULL",
                    (slug,),
                ).fetchall()
                kind_map = {r["belief_id"]: r["source_kind"] or "unknown" for r in sk_rows}
            except Exception:
                pass

        if not beliefs and not history:
            return f"No beliefs found for `{query}` in workspace `{slug}`."

        current = [b for b in beliefs if b.is_current]
        superseded = [b for b in beliefs if not b.is_current] + history

        parts = [f'## Beliefs matching "{query}"\n']

        if current:
            parts.append("### Current beliefs\n")

            for b in current:
                kind = kind_map.get(b.belief_id, "")
                kind_label = f" [{kind}]" if kind and kind != "unknown" else ""
                parts.append(f"**{b.statement}**{kind_label}")
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
