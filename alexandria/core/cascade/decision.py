"""Cascade decision engine — decides merge vs hedge vs new_page.

Uses concept discovery (FTS + belief graph) and optional LLM classification
to determine how a new source relates to existing wiki content.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alexandria.core.cascade.discovery import (
    CandidatePage,
    find_candidate_pages,
    llm_classify_relation,
)

# Score thresholds for FTS-only fallback (no LLM)
MERGE_THRESHOLD = 0.85  # above this -> merge (conservative without LLM)
CROSSREF_THRESHOLD = 0.4  # above this -> cross_ref
# below CROSSREF_THRESHOLD -> new_page


@dataclass(frozen=True)
class CascadePlan:
    """The decision for how to handle a newly ingested source."""

    action: str  # "new_page" | "merge" | "hedge"
    target_page: str = ""
    section_heading: str = "Overview"
    cross_refs: list[str] = field(default_factory=list)
    reasoning: str = ""


def plan_cascade(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    title: str,
    body: str,
    beliefs: list[dict[str, Any]],
    *,
    exclude_path: str = "",
) -> CascadePlan:
    """Decide how to integrate a new source into the wiki."""
    candidates = find_candidate_pages(
        conn, workspace, title, beliefs, exclude_path=exclude_path,
    )

    if not candidates or candidates[0].score < CROSSREF_THRESHOLD:
        return CascadePlan(action="new_page", reasoning="no related pages found")

    top = candidates[0]

    # Try LLM classification for the top candidate
    target_path = workspace_path / top.path
    if target_path.exists():
        target_content = target_path.read_text(encoding="utf-8")
        relation = llm_classify_relation(body[:2000], target_content, top.path)

        if relation and relation.relation in ("merge", "hedge"):
            cross_refs = _collect_cross_refs(candidates[1:], top.path)
            return CascadePlan(
                action=relation.relation,
                target_page=top.path,
                section_heading=relation.section_heading,
                cross_refs=cross_refs,
                reasoning=relation.reasoning,
            )

        if relation and relation.relation == "cross_ref":
            cross_refs = [top.path] + _collect_cross_refs(candidates[1:], "")
            return CascadePlan(
                action="new_page",
                cross_refs=cross_refs,
                reasoning=f"LLM: cross_ref — {relation.reasoning}",
            )

    # FTS-only fallback (no LLM or LLM said new_page)
    if top.score >= MERGE_THRESHOLD:
        cross_refs = _collect_cross_refs(candidates[1:], top.path)
        return CascadePlan(
            action="merge",
            target_page=top.path,
            section_heading="Overview",
            cross_refs=cross_refs,
            reasoning=f"FTS score {top.score:.2f} above merge threshold",
        )

    # Below merge threshold but above cross_ref threshold
    cross_refs = _collect_cross_refs(candidates, "")
    return CascadePlan(
        action="new_page",
        cross_refs=cross_refs,
        reasoning=f"FTS score {top.score:.2f} below merge threshold, adding cross-refs",
    )


def _collect_cross_refs(
    candidates: list[CandidatePage], exclude: str,
) -> list[str]:
    """Collect cross-ref targets above the threshold, excluding one path."""
    return [
        c.path for c in candidates
        if c.score >= CROSSREF_THRESHOLD and c.path != exclude
    ][:5]
