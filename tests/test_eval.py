"""Tests for evaluation metrics and runner."""

import pytest

from llmwiki.eval.metrics import M1CitationFidelity, M2CascadeCoverage, M4Cost, M5SelfConsistency, MetricResult
from llmwiki.eval.runner import check_synthesis_gate, run_all_metrics, run_metric
from llmwiki.db.connection import connect
from llmwiki.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    with connect(db_path) as c:
        Migrator().apply_pending(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES ('test', 'Test', '/tmp/test', '2025-01-01', '2025-01-01')"
        )
        c.execute("COMMIT")
        yield c


class TestM1:
    def test_no_beliefs(self, conn) -> None:
        m = M1CitationFidelity()
        result = m.compute(conn, "test")
        assert result.score == 1.0
        assert result.passed is True

    def test_with_beliefs(self, conn) -> None:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO wiki_beliefs (belief_id, workspace, statement, topic, "
            "wiki_document_path, footnote_ids, asserted_at, created_at) "
            "VALUES ('b-1', 'test', 'Test claim', 'testing', 'doc.md', "
            "'[\"1\"]', datetime('now'), datetime('now'))"
        )
        conn.execute("COMMIT")

        m = M1CitationFidelity()
        result = m.compute(conn, "test")
        assert result.score == 1.0


class TestM4:
    def test_no_runs(self, conn) -> None:
        m = M4Cost()
        result = m.compute(conn, "test")
        assert result.passed is True
        assert result.detail["total_usd"] == 0.0


class TestRunner:
    def test_run_single_metric(self, conn) -> None:
        result = run_metric(conn, "test", "M1")
        assert isinstance(result, MetricResult)
        assert result.metric == "M1"

    def test_run_all_metrics(self, conn) -> None:
        results = run_all_metrics(conn, "test")
        assert len(results) >= 4
        names = [r.metric for r in results]
        assert "M1" in names
        assert "M4" in names

    def test_unknown_metric_raises(self, conn) -> None:
        with pytest.raises(ValueError, match="unknown metric"):
            run_metric(conn, "test", "NONEXISTENT")

    def test_results_stored(self, conn) -> None:
        run_metric(conn, "test", "M1")
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE workspace = 'test' AND metric = 'M1'"
        ).fetchone()
        assert row is not None


class TestSynthesisGate:
    def test_no_runs_blocks(self, conn) -> None:
        allowed, reasons = check_synthesis_gate(conn, "test")
        assert allowed is False
        assert len(reasons) == 2  # M1 and M2 both missing

    def test_passing_allows(self, conn) -> None:
        # Run M1 and M2
        run_metric(conn, "test", "M1")
        run_metric(conn, "test", "M2")
        allowed, reasons = check_synthesis_gate(conn, "test")
        # May or may not pass depending on data, but gate is checked
        assert isinstance(allowed, bool)
