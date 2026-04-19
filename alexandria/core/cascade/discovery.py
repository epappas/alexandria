"""Concept discovery — find existing wiki pages covering the same topic.

Two-layer matching:
1. FTS-only (no LLM): hybrid search on title + belief subject overlap
2. LLM-enhanced: ask the LLM to classify the relationship
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from alexandria.core.beliefs.repository import find_beliefs_by_subject
from alexandria.core.search import hybrid_search


@dataclass(frozen=True)
class CandidatePage:
    """A wiki page that may cover the same concept as an incoming source."""

    path: str
    title: str
    score: float
    match_reason: str  # "fts" | "belief_subject" | "llm"


@dataclass(frozen=True)
class ConceptRelation:
    """LLM classification of how a new source relates to an existing page."""

    relation: str  # "merge" | "hedge" | "new_page" | "cross_ref"
    target_page: str
    section_heading: str
    reasoning: str


def find_candidate_pages(
    conn: sqlite3.Connection,
    workspace: str,
    title: str,
    beliefs: list[dict[str, Any]],
    *,
    exclude_path: str = "",
    limit: int = 5,
) -> list[CandidatePage]:
    """Find existing wiki pages covering the same concept. No LLM needed."""
    seen: dict[str, CandidatePage] = {}

    # 1. Direct title similarity — most reliable signal
    _title_search(conn, workspace, title, seen)

    # 2. Hybrid search on the title (FTS + recency + beliefs)
    for hit in hybrid_search(conn, workspace, title, limit=limit):
        if hit.layer != "wiki" or hit.path in seen:
            continue
        seen[hit.path] = CandidatePage(
            path=hit.path, title=hit.title, score=hit.score * 0.8,
            match_reason="fts",
        )

    # 3. Belief subject overlap
    for b in beliefs:
        subj = b.get("subject")
        if not subj:
            continue
        related = find_beliefs_by_subject(conn, workspace, subj, limit=5)
        for rb in related:
            p = rb.wiki_document_path
            if p and p not in seen and p.startswith("wiki/"):
                seen[p] = CandidatePage(
                    path=p, title=subj, score=0.5, match_reason="belief_subject",
                )

    # Remove self-matches
    if exclude_path:
        seen.pop(exclude_path, None)

    candidates = sorted(seen.values(), key=lambda c: c.score, reverse=True)
    return candidates[:limit]


def _title_search(
    conn: sqlite3.Connection,
    workspace: str,
    title: str,
    seen: dict[str, CandidatePage],
) -> None:
    """Find wiki pages with similar titles using word overlap."""
    import re
    title_words = {
        w.lower() for w in re.findall(r'[a-zA-Z]{3,}', title)
    } - _TITLE_STOP_WORDS

    if not title_words:
        return

    rows = conn.execute(
        "SELECT path, title FROM documents WHERE workspace = ? AND layer = 'wiki'",
        (workspace,),
    ).fetchall()

    for row in rows:
        page_title = row["title"] or ""
        page_words = {
            w.lower() for w in re.findall(r'[a-zA-Z]{3,}', page_title)
        } - _TITLE_STOP_WORDS

        if not page_words:
            continue

        overlap = len(title_words & page_words)
        min_size = min(len(title_words), len(page_words))
        if min_size == 0:
            continue

        # Overlap coefficient: intersection / min(|A|, |B|)
        # Better than Jaccard for asymmetric title matching
        coeff = overlap / min_size
        if coeff >= 0.3 and overlap >= 1:
            # Title matches are high-confidence — boost above FTS noise
            score = 0.6 + (coeff * 0.4)  # range: [0.72, 1.0]
            seen[row["path"]] = CandidatePage(
                path=row["path"], title=page_title,
                score=score, match_reason="title",
            )


_TITLE_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "has", "have", "its", "can", "how", "new", "via", "using", "based",
    "learning", "test", "time", "model", "models",
})


def llm_classify_relation(
    source_summary: str,
    candidate_content: str,
    candidate_path: str,
) -> ConceptRelation | None:
    """Ask the LLM to classify the relationship. Returns None if no LLM."""
    from alexandria.core.llm_ingest import _get_provider
    from alexandria.llm.base import CompletionRequest, Message

    provider = _get_provider()
    if provider is None:
        return None

    prompt = (
        f"You are classifying the relationship between a new source and an existing wiki page.\n\n"
        f"## Existing wiki page ({candidate_path}):\n{candidate_content[:3000]}\n\n"
        f"## New source summary:\n{source_summary[:2000]}\n\n"
        f"Classify as ONE of:\n"
        f'- "merge" — new source elaborates/extends the existing page (same concept, more detail)\n'
        f'- "hedge" — new source contradicts a claim on the existing page\n'
        f'- "cross_ref" — related but different concept (deserves a See Also link)\n'
        f'- "new_page" — unrelated, should be a separate page\n\n'
        f'Respond with JSON: {{"relation": "...", "section_heading": "Overview", "reasoning": "..."}}'
    )

    request = CompletionRequest(
        model="",
        system=[{"type": "text", "text": "Classify concept relationships. Return only JSON."}],
        tools=[],
        messages=[Message(role="user", content=[{"type": "text", "text": prompt}])],
        max_output_tokens=500,
        temperature=0.1,
    )

    try:
        result = provider.complete(request)
    except RuntimeError:
        return None

    return _parse_relation(result.text, candidate_path)


def _parse_relation(text: str, candidate_path: str) -> ConceptRelation | None:
    """Parse the LLM's JSON response into a ConceptRelation."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(ln for ln in lines if not ln.startswith("```"))

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    relation = data.get("relation", "")
    if relation not in ("merge", "hedge", "cross_ref", "new_page"):
        return None

    return ConceptRelation(
        relation=relation,
        target_page=candidate_path,
        section_heading=data.get("section_heading", "Overview"),
        reasoning=data.get("reasoning", ""),
    )
