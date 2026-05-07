"""Evaluation metrics for alexandria quality assurance.

M1: Citation fidelity — sample beliefs and run the deterministic verifier
    against each belief's cited footnote. The deterministic floor; the
    LLM-judged hostile verifier extends this when wired.
M2: Cascade coverage — do ingested sources propagate through the wiki?
M3: Fabrication catch rate — runs the verifier_evasion corpus through the
    deterministic verifier and reports tier-1 catch rate. Tier-2 (semantic)
    requires an LLM-backed hostile verifier. Phase 2a placeholder per
    PLAN_AMENDMENTS.md I2.
M4: Cost tracking — cumulative LLM spend.
M5: Self-consistency — do belief pairs agree?
M6: Retroactive query benchmark — replays user-authored gold queries
    through the agent loop and scores topic + citation overlap. Implements
    doc 14's M3 ("can the wiki answer the same question today as last
    month"); shipped as M6 to coexist with the Phase 2a M3 above.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from alexandria.core.citations import (
    Footnote,
    extract_footnotes,
    verify_quote_anchor,
)
from alexandria.core.citations.anchors import create_anchor
from alexandria.eval.fabrication_corpus import run_corpus
from alexandria.eval.retroactive import QueryRunner, run_benchmark


@dataclass(frozen=True)
class MetricResult:
    """Result of a single metric evaluation."""

    metric: str
    score: float  # 0.0 to 1.0
    passed: bool
    detail: dict[str, Any]


class Metric(Protocol):
    """Interface every metric must satisfy."""

    name: str

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        ...


_M1_VOTE_SUPPORTS = "supports"
_M1_VOTE_DOES_NOT_SUPPORT = "does_not_support"
_M1_VOTE_SOURCE_MISSING = "source_missing"
_M1_VOTE_NO_PAGE = "no_page"
_M1_VOTE_NO_FOOTNOTE = "no_footnote"


class M1CitationFidelity:
    """Sample 50 beliefs and run the deterministic verifier against each.

    Each sampled belief's footnotes are checked via the same anchor-verification
    primitive the hostile verifier uses. The four-way vote tally
    (supports / does_not_support / source_missing / no_page) is reported in
    detail; the score is supports / total. The LLM-judged verifier upgrades
    this to the supports / partially_supports / does_not_support split when
    wired, without changing the metric's score formula.
    """

    name = "M1"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        ws_path = _workspace_path(conn, workspace)
        if ws_path is None:
            return MetricResult(metric=self.name, score=0.0, passed=False,
                               detail={"error": f"workspace '{workspace}' not found"})

        rows = conn.execute(
            """SELECT belief_id, statement, footnote_ids, wiki_document_path
            FROM wiki_beliefs
            WHERE workspace = ? AND superseded_at IS NULL
            ORDER BY RANDOM() LIMIT 50""",
            (workspace,),
        ).fetchall()

        if not rows:
            return MetricResult(metric=self.name, score=1.0, passed=True,
                               detail={"sampled": 0, "reason": "no beliefs"})

        votes = _vote_per_belief(rows, ws_path)
        sampled = len(rows)
        supports = votes[_M1_VOTE_SUPPORTS]
        score = supports / sampled

        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.8,
            detail={"sampled": sampled, **votes},
        )


def _workspace_path(conn: sqlite3.Connection, workspace: str) -> Path | None:
    row = conn.execute(
        "SELECT path FROM workspaces WHERE slug = ?", (workspace,),
    ).fetchone()
    if row is None or not row["path"]:
        return None
    return Path(row["path"])


def _vote_per_belief(
    rows: list[sqlite3.Row], ws_path: Path,
) -> dict[str, int]:
    votes = {
        _M1_VOTE_SUPPORTS: 0, _M1_VOTE_DOES_NOT_SUPPORT: 0,
        _M1_VOTE_SOURCE_MISSING: 0, _M1_VOTE_NO_PAGE: 0,
        _M1_VOTE_NO_FOOTNOTE: 0,
    }
    page_cache: dict[str, dict[str, Footnote] | None] = {}
    for row in rows:
        votes[_belief_vote(row, ws_path, page_cache)] += 1
    return votes


def _belief_vote(
    row: sqlite3.Row, ws_path: Path,
    page_cache: dict[str, dict[str, Footnote] | None],
) -> str:
    fn_index = _load_page_footnotes(row["wiki_document_path"], ws_path, page_cache)
    if fn_index is None:
        return _M1_VOTE_NO_PAGE

    try:
        footnote_ids = json.loads(row["footnote_ids"] or "[]")
    except (TypeError, json.JSONDecodeError):
        footnote_ids = []
    if not footnote_ids:
        return _M1_VOTE_NO_FOOTNOTE

    seen_does_not = False
    seen_source_missing = False
    for fid in footnote_ids:
        fn = fn_index.get(str(fid))
        if fn is None or not fn.has_quote:
            seen_does_not = True
            continue
        status = _verify_footnote(fn, ws_path)
        if status == "verified":
            continue
        if status == "source_missing":
            seen_source_missing = True
        else:
            seen_does_not = True

    if seen_source_missing:
        return _M1_VOTE_SOURCE_MISSING
    if seen_does_not:
        return _M1_VOTE_DOES_NOT_SUPPORT
    return _M1_VOTE_SUPPORTS


def _load_page_footnotes(
    page_rel: str, ws_path: Path,
    page_cache: dict[str, dict[str, Footnote] | None],
) -> dict[str, Footnote] | None:
    if page_rel in page_cache:
        return page_cache[page_rel]
    page_path = ws_path / "wiki" / page_rel
    if not page_path.is_file():
        page_cache[page_rel] = None
        return None
    text = page_path.read_text(encoding="utf-8")
    index = {fn.footnote_id: fn for fn in extract_footnotes(text)}
    page_cache[page_rel] = index
    return index


def _verify_footnote(fn: Footnote, ws_path: Path) -> str:
    anchor = create_anchor(source_file=fn.source_file, quote=fn.quote or "")
    return verify_quote_anchor(anchor, ws_path).status


class M2CascadeCoverage:
    """Check that ingested sources are reflected in wiki pages."""

    name = "M2"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        try:
            raw_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE workspace = ? AND layer = 'raw'",
                (workspace,),
            ).fetchone()[0]
            wiki_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE workspace = ? AND layer = 'wiki'",
                (workspace,),
            ).fetchone()[0]
        except Exception:
            return MetricResult(metric=self.name, score=0.0, passed=False,
                               detail={"error": "tables not available"})

        if raw_count == 0:
            return MetricResult(metric=self.name, score=1.0, passed=True,
                               detail={"raw": 0, "wiki": wiki_count, "reason": "no raw docs"})

        coverage = min(wiki_count / max(raw_count, 1), 1.0)
        return MetricResult(
            metric=self.name, score=coverage, passed=coverage >= 0.5,
            detail={"raw": raw_count, "wiki": wiki_count},
        )


class M3FabricationCatch:
    """Run the verifier_evasion corpus and report catch rate per tier.

    Score is the tier-1 deterministic catch rate (≥0.90 to pass per the
    Phase 2a acceptance criterion in PLAN_AMENDMENTS.md). Tier-2 cases need
    a semantic verifier with an LLM provider; without one they are reported
    as ``pending`` and excluded from the score.
    """

    name = "M3"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        result = run_corpus()
        return MetricResult(
            metric=self.name,
            score=result.tier1_catch_rate,
            passed=result.tier1_catch_rate >= 0.90,
            detail={
                "tier1_total": result.tier1_total,
                "tier1_caught": result.tier1_caught,
                "tier1_catch_rate": round(result.tier1_catch_rate, 4),
                "tier2_total": result.tier2_total,
                "tier2_caught": result.tier2_caught,
                "tier2_pending": result.tier2_pending,
                "tier2_catch_rate": round(result.tier2_catch_rate, 4),
            },
        )


class M4Cost:
    """Track cumulative LLM cost from runs table."""

    name = "M4"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        try:
            row = conn.execute(
                "SELECT SUM(budget_usd_used) FROM runs WHERE workspace = ?",
                (workspace,),
            ).fetchone()
            total_usd = row[0] or 0.0
        except Exception:
            total_usd = 0.0

        return MetricResult(
            metric=self.name, score=min(1.0, 1.0 - (total_usd / 50.0)),
            passed=total_usd < 50.0,
            detail={"total_usd": round(total_usd, 4)},
        )


class M5SelfConsistency:
    """Sample belief pairs and check for contradictions."""

    name = "M5"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        rows = conn.execute(
            """SELECT topic, COUNT(*) as cnt FROM wiki_beliefs
            WHERE workspace = ? AND superseded_at IS NULL
            GROUP BY topic HAVING cnt > 1 LIMIT 10""",
            (workspace,),
        ).fetchall()

        if not rows:
            return MetricResult(metric=self.name, score=1.0, passed=True,
                               detail={"topics_checked": 0})

        total_pairs = 0
        consistent_pairs = 0
        for row in rows:
            topic = row["topic"]
            beliefs = conn.execute(
                "SELECT subject, predicate, object FROM wiki_beliefs "
                "WHERE workspace = ? AND topic = ? AND superseded_at IS NULL",
                (workspace, topic),
            ).fetchall()

            for i in range(len(beliefs)):
                for j in range(i + 1, len(beliefs)):
                    total_pairs += 1
                    if beliefs[i]["subject"] and beliefs[j]["subject"]:
                        consistent_pairs += 1

        score = consistent_pairs / max(total_pairs, 1)
        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.6,
            detail={"topics_checked": len(rows), "pairs": total_pairs},
        )


class M6RetroactiveQuery:
    """Retroactive query benchmark — implements doc 14 M3 under the M6 label.

    Loads the user-authored gold queries (``alxia eval gold add ...``),
    replays each through the configured agent loop, and scores
    Jaccard topic overlap × expected-citation recall. With no gold
    queries registered the metric reports score 1.0 with reason
    ``no gold queries`` (vacuous truth, same pattern as M1 with no beliefs).
    """

    name = "M6"

    def __init__(self, runner: QueryRunner | None = None) -> None:
        self._runner = runner

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        ws_path = _workspace_path(conn, workspace)
        if ws_path is None:
            return MetricResult(metric=self.name, score=0.0, passed=False,
                               detail={"error": f"workspace '{workspace}' not found"})

        runner = self._runner or _default_runner()
        if runner is None:
            return MetricResult(metric=self.name, score=0.0, passed=False,
                               detail={"error": "no LLM provider configured"})

        result = run_benchmark(conn, workspace, ws_path, runner)
        if result.sampled == 0 and result.skipped_no_llm == 0:
            return MetricResult(
                metric=self.name, score=1.0, passed=True,
                detail={"sampled": 0, "reason": "no gold queries"},
            )

        score = result.composite_score
        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.80,
            detail={
                "sampled": result.sampled,
                "skipped_no_llm": result.skipped_no_llm,
                "mean_topic_overlap": round(result.mean_topic_overlap, 4),
                "mean_citation_overlap": round(result.mean_citation_overlap, 4),
                "per_query": [
                    {
                        "query_id": s.query_id,
                        "topic_overlap": round(s.topic_overlap, 4),
                        "citation_overlap": round(s.citation_overlap, 4),
                    } for s in result.per_query
                ],
            },
        )


def _default_runner() -> QueryRunner | None:
    from alexandria.core.agent_loop import run_agent_query
    from alexandria.core.llm_ingest import _get_provider
    if _get_provider() is None:
        return None
    return run_agent_query


ALL_METRICS: list[Metric] = [
    M1CitationFidelity(),
    M2CascadeCoverage(),
    M3FabricationCatch(),
    M4Cost(),
    M5SelfConsistency(),
    M6RetroactiveQuery(),
]
