"""Hybrid search — combines FTS5 BM25, recency decay, and belief support.

Three signals scored and merged with configurable weights:
- **Relevance** (BM25): FTS5 rank, normalized to [0, 1].
- **Recency**: Exponential decay from ``updated_at``, half-life configurable.
- **Belief support**: Number of current beliefs referencing the document.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from alexandria.db.connection import sanitize_fts_query


@dataclass(frozen=True)
class HybridWeights:
    """Weights for each scoring signal. Must sum to 1.0."""

    relevance: float = 0.55
    recency: float = 0.30
    belief: float = 0.15


@dataclass
class SearchHit:
    """A single search result with composite score breakdown."""

    doc_id: str
    path: str
    title: str
    layer: str
    content: str
    score: float
    relevance_score: float = 0.0
    recency_score: float = 0.0
    belief_score: float = 0.0
    belief_count: int = 0


DEFAULT_WEIGHTS = HybridWeights()
RECENCY_HALF_LIFE_HOURS = 168.0  # 7 days


def hybrid_search(
    conn: sqlite3.Connection,
    workspace: str,
    query: str,
    *,
    limit: int = 10,
    weights: HybridWeights = DEFAULT_WEIGHTS,
    half_life_hours: float = RECENCY_HALF_LIFE_HOURS,
) -> list[SearchHit]:
    """Run a hybrid search combining BM25, recency, and belief signals."""
    fts_query = sanitize_fts_query(query)

    # 1. FTS5 search — get candidates with BM25 rank
    try:
        rows = conn.execute(
            """SELECT d.id, d.path, d.title, d.layer, d.content, d.updated_at,
                      f.rank as bm25_rank
            FROM documents_fts f
            JOIN documents d ON d.rowid = f.rowid
            WHERE f.documents_fts MATCH ? AND d.workspace = ?
            ORDER BY f.rank
            LIMIT ?""",
            (fts_query, workspace, limit * 3),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    if not rows:
        return []

    # 2. Normalize BM25 ranks to [0, 1] (rank is negative, closer to 0 = better)
    ranks = [r["bm25_rank"] for r in rows]
    worst = min(ranks)  # most negative = worst
    best = max(ranks)   # closest to 0 = best
    rank_range = best - worst if best != worst else 1.0

    # 3. Get belief counts per document path
    belief_counts = _belief_counts_for_paths(
        conn, workspace, [r["path"] for r in rows]
    )

    # 4. Score each hit
    now = datetime.now(timezone.utc)
    hits: list[SearchHit] = []

    for row in rows:
        # Relevance: normalize BM25 rank to [0, 1]
        rel = (row["bm25_rank"] - worst) / rank_range if rank_range else 1.0

        # Recency: exponential decay from updated_at
        rec = _recency_score(row["updated_at"], now, half_life_hours)

        # Belief support: log-scaled count
        bc = belief_counts.get(row["path"], 0)
        bel = min(1.0, math.log1p(bc) / math.log1p(5))  # 5+ beliefs = 1.0

        # Composite
        score = (
            weights.relevance * rel
            + weights.recency * rec
            + weights.belief * bel
        )

        hits.append(SearchHit(
            doc_id=row["id"],
            path=row["path"],
            title=row["title"] or "",
            layer=row["layer"],
            content=row["content"] or "",
            score=score,
            relevance_score=rel,
            recency_score=rec,
            belief_score=bel,
            belief_count=bc,
        ))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def _recency_score(
    updated_at: str, now: datetime, half_life_hours: float,
) -> float:
    """Exponential decay score. Returns 1.0 for now, 0.5 at half_life."""
    try:
        updated = datetime.fromisoformat(updated_at)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0
    age_hours = max(0.0, (now - updated).total_seconds() / 3600)
    return math.exp(-age_hours * math.log(2) / half_life_hours)


def _belief_counts_for_paths(
    conn: sqlite3.Connection,
    workspace: str,
    paths: list[str],
) -> dict[str, int]:
    """Count current beliefs referencing each document path."""
    if not paths:
        return {}
    placeholders = ", ".join("?" for _ in paths)
    rows = conn.execute(
        f"""SELECT wiki_document_path, COUNT(*) as cnt
        FROM wiki_beliefs
        WHERE workspace = ? AND superseded_at IS NULL
          AND wiki_document_path IN ({placeholders})
        GROUP BY wiki_document_path""",
        [workspace, *paths],
    ).fetchall()
    return {r["wiki_document_path"]: r["cnt"] for r in rows}
