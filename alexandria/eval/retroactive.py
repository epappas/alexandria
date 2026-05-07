"""Retroactive query benchmark — runs gold queries through the agent loop
and scores topic + citation overlap against the user-authored expectations.

Implements doc 14's M3 ("retroactive query benchmark"): can the wiki
answer the same question today that it answered last month, and does
the answer get better or worse over time? Shipped under the ``M6``
label to coexist with the Phase 2a fabrication-catch metric already
registered as M3 (see ``PLAN_AMENDMENTS.md`` I2).

Score: ``mean(topic_overlap) × mean(citation_overlap)``. Pass ≥ 0.80.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alexandria.eval.gold import GoldQuery, list_gold

QueryRunner = Callable[
    [sqlite3.Connection, str, Path, str], dict[str, Any] | None,
]

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_CITATION_INLINE_RE = re.compile(r"\[Source:\s*([^\]]+)\]")
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "into", "onto", "over",
    "under", "between", "about", "against", "before", "after", "above", "below",
    "have", "has", "had", "having", "are", "was", "were", "been", "being", "but",
    "not", "all", "any", "which", "what", "when", "who", "whom", "whose",
    "where", "why", "how", "your", "yours", "their", "theirs", "ours", "they",
    "them", "his", "her", "him", "she", "you", "yourself", "themselves",
    "would", "could", "should", "will", "shall", "may", "might", "must",
    "does", "did", "doing", "done", "say", "said", "says", "such", "some",
    "many", "more", "most", "other", "than", "then", "there", "here", "very",
    "just", "also", "only", "even", "still", "yet", "thus", "hence",
    "however", "therefore",
})


@dataclass(frozen=True)
class QueryScore:
    """Score for one gold query against an actual agent answer."""

    query_id: str
    query: str
    topic_overlap: float
    citation_overlap: float
    actual_topics: list[str]
    actual_citations: list[str]
    expected_topics: list[str]
    expected_citations: list[str]
    answer: str


@dataclass(frozen=True)
class BenchmarkResult:
    """Aggregate result of running every gold query."""

    per_query: list[QueryScore]
    sampled: int
    skipped_no_llm: int
    mean_topic_overlap: float
    mean_citation_overlap: float

    @property
    def composite_score(self) -> float:
        return self.mean_topic_overlap * self.mean_citation_overlap


def extract_topics(text: str) -> set[str]:
    """Extract a normalized topic set from free-form answer text.

    Tokens of length ≥ 3 letters, lowercased, stopwords stripped. The
    project's CLAUDE.md forbids heuristic NLP libs in the hot path; this
    is the deterministic floor used for scoring. The LLM-judged variant
    can layer on top later.
    """
    if not text:
        return set()
    return {
        tok.lower() for tok in _TOKEN_RE.findall(text)
        if tok.lower() not in _STOPWORDS
    }


def extract_citations(answer: dict[str, Any]) -> set[str]:
    """Pull cited source paths from an agent answer.

    Reads two locations:
    1. The structured ``sources`` list returned by the ``answer`` tool,
       using each entry's ``path`` field.
    2. Inline ``[Source: <path>]`` markers in the answer text — the agent
       loop prompt instructs the LLM to emit these.
    """
    paths: set[str] = set()
    for src in answer.get("sources") or []:
        if isinstance(src, dict):
            path = src.get("path") or src.get("title")
            if path:
                paths.add(_normalize_citation(path))
    for match in _CITATION_INLINE_RE.finditer(answer.get("answer", "") or ""):
        paths.add(_normalize_citation(match.group(1)))
    return paths


def topic_jaccard(actual: set[str], expected: set[str]) -> float:
    """Jaccard similarity over normalized topic sets."""
    if not expected and not actual:
        return 1.0
    if not expected:
        return 0.0
    expected_norm = {t.lower() for t in expected}
    actual_norm = {t.lower() for t in actual}
    intersection = expected_norm & actual_norm
    union = expected_norm | actual_norm
    return len(intersection) / len(union) if union else 0.0


def citation_overlap(actual: set[str], expected: set[str]) -> float:
    """Recall over the expected citation set: |actual ∩ expected| / |expected|."""
    if not expected:
        return 1.0
    expected_norm = {_normalize_citation(c) for c in expected}
    actual_norm = {_normalize_citation(c) for c in actual}
    hits = expected_norm & actual_norm
    return len(hits) / len(expected_norm)


def score_query(answer: dict[str, Any], gold: GoldQuery) -> QueryScore:
    """Score one gold query against the agent's actual answer."""
    actual_topics = extract_topics(answer.get("answer", ""))
    actual_citations = extract_citations(answer)
    return QueryScore(
        query_id=gold.query_id,
        query=gold.query,
        topic_overlap=topic_jaccard(actual_topics, set(gold.expected_topics)),
        citation_overlap=citation_overlap(actual_citations, set(gold.expected_citations)),
        actual_topics=sorted(actual_topics),
        actual_citations=sorted(actual_citations),
        expected_topics=list(gold.expected_topics),
        expected_citations=list(gold.expected_citations),
        answer=answer.get("answer", ""),
    )


def run_benchmark(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    runner: QueryRunner,
) -> BenchmarkResult:
    """Replay every gold query through ``runner`` and aggregate scores."""
    golds = list_gold(conn, workspace)
    if not golds:
        return BenchmarkResult([], 0, 0, 1.0, 1.0)

    per_query: list[QueryScore] = []
    skipped = 0
    for gold in golds:
        answer = runner(conn, workspace, workspace_path, gold.query)
        if answer is None:
            skipped += 1
            continue
        per_query.append(score_query(answer, gold))

    sampled = len(per_query)
    if sampled == 0:
        return BenchmarkResult([], 0, skipped, 0.0, 0.0)

    mean_topic = sum(s.topic_overlap for s in per_query) / sampled
    mean_citation = sum(s.citation_overlap for s in per_query) / sampled
    return BenchmarkResult(per_query, sampled, skipped, mean_topic, mean_citation)


def _normalize_citation(path: str) -> str:
    """Lowercase + strip surrounding whitespace and trailing punctuation."""
    return path.strip().rstrip(".,;").lower()
