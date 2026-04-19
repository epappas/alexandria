"""REST API endpoints for the web dashboard.

Served alongside the MCP HTTP server on the same port.
Provides JSON endpoints for stats, search, beliefs, and documents.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from alexandria.config import resolve_home
from alexandria.db.connection import connect, db_path

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _validate_workspace(workspace: str) -> str | None:
    """Validate workspace slug. Returns None if invalid."""
    if _SLUG_RE.match(workspace):
        return workspace
    return None


def _safe_int(val: str, default: int, max_val: int) -> int:
    """Parse an integer from query params with bounds."""
    try:
        return min(int(val), max_val)
    except (ValueError, TypeError):
        return default


async def stats_handler(request: Request) -> Response:
    """GET /api/stats — workspace statistics."""
    from starlette.responses import JSONResponse

    home = resolve_home()
    workspace = _validate_workspace(request.query_params.get("workspace", "global"))
    if not workspace:
        return JSONResponse({"error": "invalid workspace"}, status_code=400)

    if not db_path(home).exists():
        return JSONResponse({"error": "no database"}, status_code=500)

    with connect(db_path(home)) as conn:
        docs = conn.execute(
            "SELECT COUNT(*) as c FROM documents WHERE workspace = ?", (workspace,)
        ).fetchone()
        wiki = conn.execute(
            "SELECT COUNT(*) as c FROM documents WHERE workspace = ? AND layer = 'wiki'", (workspace,)
        ).fetchone()
        beliefs = conn.execute(
            "SELECT COUNT(*) as c FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NULL", (workspace,)
        ).fetchone()
        topics = conn.execute(
            "SELECT DISTINCT topic FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NULL ORDER BY topic",
            (workspace,),
        ).fetchall()
        runs = conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()

    return JSONResponse({
        "workspace": workspace,
        "documents": docs["c"],
        "wiki_pages": wiki["c"],
        "raw_sources": docs["c"] - wiki["c"],
        "beliefs": beliefs["c"],
        "topics": [r["topic"] for r in topics],
        "runs": runs["c"],
    })


async def search_handler(request: Request) -> Response:
    """GET /api/search?q=...&limit=10 — hybrid search."""
    from starlette.responses import JSONResponse

    from alexandria.core.search import hybrid_search

    home = resolve_home()
    query = request.query_params.get("q", "")
    workspace = _validate_workspace(request.query_params.get("workspace", "global"))
    if not workspace:
        return JSONResponse({"error": "invalid workspace"}, status_code=400)
    limit = _safe_int(request.query_params.get("limit", "10"), 10, 50)

    if not query:
        return JSONResponse({"error": "q parameter required"}, status_code=400)

    with connect(db_path(home)) as conn:
        hits = hybrid_search(conn, workspace, query, limit=limit)

    return JSONResponse({
        "query": query,
        "results": [
            {
                "path": h.path,
                "title": h.title,
                "score": round(h.score, 3),
                "layer": h.layer,
                "belief_count": h.belief_count,
                "snippet": h.content[:300],
            }
            for h in hits
        ],
    })


async def beliefs_handler(request: Request) -> Response:
    """GET /api/beliefs?topic=...&limit=50 — list beliefs."""
    from starlette.responses import JSONResponse

    from alexandria.core.beliefs.repository import list_beliefs

    home = resolve_home()
    workspace = _validate_workspace(request.query_params.get("workspace", "global"))
    if not workspace:
        return JSONResponse({"error": "invalid workspace"}, status_code=400)
    topic = request.query_params.get("topic")
    limit = _safe_int(request.query_params.get("limit", "50"), 50, 200)

    with connect(db_path(home)) as conn:
        beliefs = list_beliefs(conn, workspace, topic=topic, limit=limit)

    return JSONResponse({
        "beliefs": [
            {
                "belief_id": b.belief_id,
                "statement": b.statement,
                "topic": b.topic,
                "subject": b.subject,
                "predicate": b.predicate,
                "object": b.object,
                "asserted_at": b.asserted_at,
                "wiki_path": b.wiki_document_path,
            }
            for b in beliefs
        ],
    })


async def documents_handler(request: Request) -> Response:
    """GET /api/documents?path=... — read a document."""
    from starlette.responses import JSONResponse

    home = resolve_home()
    workspace = _validate_workspace(request.query_params.get("workspace", "global"))
    if not workspace:
        return JSONResponse({"error": "invalid workspace"}, status_code=400)
    doc_path = request.query_params.get("path", "")
    # Prevent path traversal
    if ".." in doc_path or doc_path.startswith("/"):
        return JSONResponse({"error": "invalid path"}, status_code=400)

    if not doc_path:
        return JSONResponse({"error": "path parameter required"}, status_code=400)

    with connect(db_path(home)) as conn:
        row = conn.execute(
            "SELECT title, content, layer, updated_at FROM documents WHERE workspace = ? AND path = ? LIMIT 1",
            (workspace, doc_path),
        ).fetchone()

    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)

    return JSONResponse({
        "path": doc_path,
        "title": row["title"],
        "content": row["content"] or "",
        "layer": row["layer"],
        "updated_at": row["updated_at"],
    })
