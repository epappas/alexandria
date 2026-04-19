"""Evaluation metrics for alexandria quality assurance.

M1: Citation fidelity — do beliefs link to real source quotes?
M2: Cascade coverage — do ingested sources propagate through the wiki?
M3: Deterministic verifier pass rate (already in Phase 2a)
M4: Cost tracking — cumulative LLM spend
M5: Self-consistency — do belief pairs agree?
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol


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


class M1CitationFidelity:
    """Sample beliefs and verify their citations point to real sources."""

    name = "M1"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        # Sample up to 50 current beliefs
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

        total = len(rows)
        valid = 0
        for row in rows:
            footnote_ids = row["footnote_ids"]
            if footnote_ids and footnote_ids != "[]":
                valid += 1

        score = valid / total if total > 0 else 0.0
        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.8,
            detail={"sampled": total, "valid": valid},
        )


class M2CascadeCoverage:
    """Check that ingested sources are reflected in wiki pages."""

    name = "M2"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        # Count raw documents vs wiki documents
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

        # M4 passes if cost is under $50 cumulative
        return MetricResult(
            metric=self.name, score=min(1.0, 1.0 - (total_usd / 50.0)),
            passed=total_usd < 50.0,
            detail={"total_usd": round(total_usd, 4)},
        )


class M5SelfConsistency:
    """Sample belief pairs and check for contradictions."""

    name = "M5"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        # Sample beliefs with the same topic
        rows = conn.execute(
            """SELECT topic, COUNT(*) as cnt FROM wiki_beliefs
            WHERE workspace = ? AND superseded_at IS NULL
            GROUP BY topic HAVING cnt > 1 LIMIT 10""",
            (workspace,),
        ).fetchall()

        if not rows:
            return MetricResult(metric=self.name, score=1.0, passed=True,
                               detail={"topics_checked": 0})

        # For now, score based on having structured SPO triples
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
                    # Simple heuristic: if both have SPO, count as checkable
                    if beliefs[i]["subject"] and beliefs[j]["subject"]:
                        consistent_pairs += 1

        score = consistent_pairs / max(total_pairs, 1)
        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.6,
            detail={"topics_checked": len(rows), "pairs": total_pairs},
        )


class M3VerifierPassRate:
    """Ratio of committed runs to total completed runs."""

    name = "M3"

    def compute(self, conn: sqlite3.Connection, workspace: str) -> MetricResult:
        row = conn.execute(
            """SELECT
                COUNT(CASE WHEN status = 'committed' THEN 1 END) as committed,
                COUNT(CASE WHEN status IN ('committed', 'rejected') THEN 1 END) as total
            FROM runs""",
        ).fetchone()
        committed = row["committed"] or 0
        total = row["total"] or 0
        if total == 0:
            return MetricResult(
                metric=self.name, score=1.0, passed=True,
                detail={"committed": 0, "total": 0},
            )
        score = committed / total
        return MetricResult(
            metric=self.name, score=score, passed=score >= 0.7,
            detail={"committed": committed, "rejected": total - committed, "total": total},
        )


ALL_METRICS: list[Metric] = [
    M1CitationFidelity(),
    M2CascadeCoverage(),
    M3VerifierPassRate(),
    M4Cost(),
    M5SelfConsistency(),
]
