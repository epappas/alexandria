"""Evaluation runner — orchestrates metric computation and stores results."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from llmwiki.eval.metrics import ALL_METRICS, MetricResult


def run_metric(
    conn: sqlite3.Connection,
    workspace: str,
    metric_name: str,
) -> MetricResult:
    """Run a single metric by name."""
    metric = next((m for m in ALL_METRICS if m.name == metric_name), None)
    if metric is None:
        raise ValueError(f"unknown metric: {metric_name}. Available: {[m.name for m in ALL_METRICS]}")

    now = datetime.now(timezone.utc).isoformat()
    run_id = f"eval-{uuid.uuid4().hex[:12]}"

    result = metric.compute(conn, workspace)

    # Store result
    conn.execute(
        """INSERT INTO eval_runs
          (run_id, workspace, metric, score, passed, detail, started_at, ended_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, workspace, result.metric, result.score,
            int(result.passed), json.dumps(result.detail), now, now,
        ),
    )

    return result


def run_all_metrics(
    conn: sqlite3.Connection,
    workspace: str,
) -> list[MetricResult]:
    """Run all metrics and return results."""
    results: list[MetricResult] = []
    for metric in ALL_METRICS:
        try:
            result = run_metric(conn, workspace, metric.name)
            results.append(result)
        except Exception as exc:
            results.append(MetricResult(
                metric=metric.name, score=0.0, passed=False,
                detail={"error": str(exc)},
            ))
    return results


def check_synthesis_gate(
    conn: sqlite3.Connection, workspace: str
) -> tuple[bool, list[str]]:
    """Check if synthesis is allowed based on M1/M2 health.

    Returns (allowed, list_of_blocking_reasons).
    """
    blocking: list[str] = []

    for metric_name in ("M1", "M2"):
        row = conn.execute(
            """SELECT score, passed FROM eval_runs
            WHERE workspace = ? AND metric = ?
            ORDER BY started_at DESC LIMIT 1""",
            (workspace, metric_name),
        ).fetchone()

        if row is None:
            blocking.append(f"{metric_name}: no evaluation run found")
        elif not row["passed"]:
            blocking.append(f"{metric_name}: score {row['score']:.2f} below threshold")

    return len(blocking) == 0, blocking
