"""Concept discovery — find existing wiki pages covering the same topic.

Two-layer matching:
1. FTS-only (no LLM): hybrid search on title + belief subject overlap
2. LLM-enhanced: ask the LLM to classify the relationship
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
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
    limit: int = 5,
) -> list[CandidatePage]:
    """Find existing wiki pages covering the same concept. No LLM needed."""
    seen: dict[str, CandidatePage] = {}

    # 1. Hybrid search on the title
    for hit in hybrid_search(conn, workspace, title, limit=limit):
        if hit.layer != "wiki":
            continue
        seen[hit.path] = CandidatePage(
            path=hit.path, title=hit.title, score=hit.score, match_reason="fts",
        )

    # 2. Belief subject overlap — find pages sharing the same subjects
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

    candidates = sorted(seen.values(), key=lambda c: c.score, reverse=True)
    return candidates[:limit]


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
        text = "\n".join(l for l in lines if not l.startswith("```"))

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
