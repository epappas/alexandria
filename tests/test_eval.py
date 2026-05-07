"""Tests for evaluation metrics and runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator
from alexandria.eval.metrics import (
    M1CitationFidelity,
    M3FabricationCatch,
    M4Cost,
    MetricResult,
)
from alexandria.eval.runner import check_synthesis_gate, run_all_metrics, run_metric


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """A real workspace dir with raw/ and wiki/ subtrees."""
    ws = tmp_path / "ws"
    (ws / "raw" / "local").mkdir(parents=True)
    (ws / "wiki" / "concepts").mkdir(parents=True)
    return ws


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path, workspace_dir: Path):
    with connect(db_path) as c:
        Migrator().apply_pending(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test", "Test", str(workspace_dir), "2025-01-01", "2025-01-01"),
        )
        c.execute("COMMIT")
        yield c


def _seed_belief(
    conn,
    workspace_dir: Path,
    *,
    page: str,
    page_body: str,
    raw_files: dict[str, str],
    footnote_ids: str = '["1"]',
    belief_id: str = "b-1",
) -> None:
    """Write a wiki page + raw sources on disk and a matching belief row."""
    page_path = workspace_dir / "wiki" / page
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(page_body, encoding="utf-8")
    for name, body in raw_files.items():
        raw_path = workspace_dir / "raw" / "local" / name
        raw_path.write_text(body, encoding="utf-8")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO wiki_beliefs (belief_id, workspace, statement, topic, "
        "wiki_document_path, footnote_ids, asserted_at, created_at) "
        "VALUES (?, 'test', 'Test claim', 'testing', ?, ?, "
        "datetime('now'), datetime('now'))",
        (belief_id, page, footnote_ids),
    )
    conn.execute("COMMIT")


class TestM1:
    def test_no_beliefs(self, conn) -> None:
        result = M1CitationFidelity().compute(conn, "test")
        assert result.score == 1.0
        assert result.passed is True
        assert result.detail["sampled"] == 0

    def test_supports_when_quote_verbatim(self, conn, workspace_dir: Path) -> None:
        """A belief whose footnote points to a verbatim quote scores supports."""
        page_body = (
            "# Concept\n\nClaim that maps to a real quote.[^1]\n\n"
            '[^1]: spec.md — "Verbatim quote in source."\n'
        )
        _seed_belief(
            conn, workspace_dir,
            page="concepts/page.md",
            page_body=page_body,
            raw_files={"spec.md": "# Spec\n\nVerbatim quote in source.\n"},
        )

        result = M1CitationFidelity().compute(conn, "test")
        assert result.score == 1.0
        assert result.passed is True
        assert result.detail["supports"] == 1
        assert result.detail["does_not_support"] == 0
        assert result.detail["source_missing"] == 0

    def test_does_not_support_when_quote_fabricated(
        self, conn, workspace_dir: Path,
    ) -> None:
        """A belief whose footnote quote is not in the source scores does_not_support."""
        page_body = (
            "# Concept\n\nFabricated claim.[^1]\n\n"
            '[^1]: spec.md — "This sentence is not in the source."\n'
        )
        _seed_belief(
            conn, workspace_dir,
            page="concepts/fab.md",
            page_body=page_body,
            raw_files={"spec.md": "# Spec\n\nA different sentence entirely.\n"},
        )

        result = M1CitationFidelity().compute(conn, "test")
        assert result.score == 0.0
        assert result.passed is False
        assert result.detail["does_not_support"] == 1

    def test_source_missing(self, conn, workspace_dir: Path) -> None:
        """A belief citing a file that is not on disk scores source_missing."""
        page_body = (
            "# Concept\n\nClaim citing a missing file.[^1]\n\n"
            '[^1]: nonexistent.md — "Some quote."\n'
        )
        _seed_belief(
            conn, workspace_dir,
            page="concepts/miss.md",
            page_body=page_body,
            raw_files={},
        )

        result = M1CitationFidelity().compute(conn, "test")
        assert result.detail["source_missing"] == 1
        assert result.score == 0.0

    def test_no_page_when_belief_path_dangling(self, conn, workspace_dir: Path) -> None:
        """A belief pointing to a wiki page that does not exist counts as no_page."""
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO wiki_beliefs (belief_id, workspace, statement, topic, "
            "wiki_document_path, footnote_ids, asserted_at, created_at) "
            "VALUES ('b-orphan', 'test', 'Orphan', 'testing', 'concepts/missing.md', "
            "'[\"1\"]', datetime('now'), datetime('now'))"
        )
        conn.execute("COMMIT")

        result = M1CitationFidelity().compute(conn, "test")
        assert result.detail["no_page"] == 1

    def test_workspace_unknown(self, conn) -> None:
        result = M1CitationFidelity().compute(conn, "does-not-exist")
        assert result.passed is False
        assert "error" in result.detail


class TestM3:
    def test_runs_corpus_and_passes_tier1_floor(self, conn) -> None:
        result = M3FabricationCatch().compute(conn, "test")
        assert result.detail["tier1_total"] >= 12
        assert result.detail["tier2_total"] >= 12
        assert result.score >= 0.90
        assert result.passed is True

    def test_tier2_pending_without_llm(self, conn) -> None:
        result = M3FabricationCatch().compute(conn, "test")
        assert result.detail["tier2_pending"] == result.detail["tier2_total"]


class TestM4:
    def test_no_runs(self, conn) -> None:
        result = M4Cost().compute(conn, "test")
        assert result.passed is True
        assert result.detail["total_usd"] == 0.0


class TestRunner:
    def test_run_single_metric(self, conn) -> None:
        result = run_metric(conn, "test", "M1")
        assert isinstance(result, MetricResult)
        assert result.metric == "M1"

    def test_run_all_metrics(self, conn) -> None:
        results = run_all_metrics(conn, "test")
        names = [r.metric for r in results]
        assert {"M1", "M2", "M3", "M4", "M5"}.issubset(set(names))

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
        assert len(reasons) == 2

    def test_passing_allows(self, conn) -> None:
        run_metric(conn, "test", "M1")
        run_metric(conn, "test", "M2")
        allowed, _ = check_synthesis_gate(conn, "test")
        assert isinstance(allowed, bool)
