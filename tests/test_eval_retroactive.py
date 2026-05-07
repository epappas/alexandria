"""Tests for the retroactive query benchmark scoring + M6 metric."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator
from alexandria.eval.gold import GoldQuery, add_gold
from alexandria.eval.metrics import M6RetroactiveQuery
from alexandria.eval.retroactive import (
    citation_overlap,
    extract_citations,
    extract_topics,
    run_benchmark,
    score_query,
    topic_jaccard,
)

# ---------- pure scoring functions ----------


def test_extract_topics_lowercases_and_drops_stopwords() -> None:
    topics = extract_topics("OAuth and PKCE are required for the new clients.")
    assert "oauth" in topics
    assert "pkce" in topics
    assert "required" in topics
    assert "and" not in topics  # stopword
    assert "the" not in topics  # stopword


def test_extract_topics_skips_short_tokens() -> None:
    topics = extract_topics("a b PKCE")
    assert topics == {"pkce"}


def test_extract_citations_reads_sources_list() -> None:
    answer = {
        "answer": "OAuth uses PKCE.",
        "sources": [{"path": "wiki/auth.md"}, {"path": "raw/oauth_spec.md"}],
    }
    assert extract_citations(answer) == {"wiki/auth.md", "raw/oauth_spec.md"}


def test_extract_citations_reads_inline_markers() -> None:
    answer = {
        "answer": "OAuth uses PKCE [Source: wiki/auth.md]. Tokens expire [Source: raw/oauth_spec.md].",
        "sources": [],
    }
    assert extract_citations(answer) == {"wiki/auth.md", "raw/oauth_spec.md"}


def test_topic_jaccard_returns_one_when_both_empty() -> None:
    assert topic_jaccard(set(), set()) == 1.0


def test_topic_jaccard_returns_zero_when_expected_empty_but_actual_nonempty() -> None:
    assert topic_jaccard({"a"}, set()) == 0.0


def test_topic_jaccard_partial_overlap() -> None:
    score = topic_jaccard({"a", "b", "c"}, {"a", "b", "d"})
    assert score == pytest.approx(2 / 4)


def test_citation_overlap_recall_semantics() -> None:
    # recall against expected: 1 of 2 expected found
    score = citation_overlap({"x.md", "extra.md"}, {"x.md", "y.md"})
    assert score == 0.5


def test_citation_overlap_one_when_expected_empty() -> None:
    assert citation_overlap({"a"}, set()) == 1.0


def test_citation_overlap_normalizes_case() -> None:
    score = citation_overlap({"Wiki/AUTH.md"}, {"wiki/auth.md"})
    assert score == 1.0


# ---------- score_query ----------


def test_score_query_combines_topic_and_citation() -> None:
    gold = GoldQuery(
        query_id="g1", workspace="w", query="What auth?",
        expected_topics=["oauth", "pkce"],
        expected_citations=["raw/oauth_spec.md"],
        created_at="2025-01-01",
    )
    answer = {
        "answer": "Auth uses OAuth with PKCE for clients.",
        "sources": [{"path": "raw/oauth_spec.md"}],
    }
    result = score_query(answer, gold)
    assert result.topic_overlap > 0
    assert result.citation_overlap == 1.0
    assert "oauth" in result.actual_topics


# ---------- run_benchmark integration ----------


@pytest.fixture
def db_with_workspace(tmp_path: Path):
    db = tmp_path / "rq.db"
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    with connect(db) as c:
        Migrator().apply_pending(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES ('w', 'Test', ?, '2025-01-01', '2025-01-01')",
            (str(ws_dir),),
        )
        c.execute("COMMIT")
        yield c, ws_dir


def _scripted_runner(answers_by_query: dict[str, dict[str, Any]]):
    """Test runner that replays canned agent answers per query string.

    This is a deliberate dependency-injection seam — the M6 metric
    accepts any QueryRunner, the production default goes through the
    real agent loop, tests inject the answers directly.
    """
    def runner(
        conn: sqlite3.Connection, workspace: str, ws_path: Path, question: str,
    ) -> dict[str, Any] | None:
        return answers_by_query.get(question)
    return runner


def test_run_benchmark_no_gold_returns_perfect(db_with_workspace) -> None:
    conn, ws_dir = db_with_workspace
    result = run_benchmark(conn, "w", ws_dir, _scripted_runner({}))
    assert result.sampled == 0
    assert result.composite_score == 1.0


def test_run_benchmark_aggregates_per_query_scores(db_with_workspace) -> None:
    conn, ws_dir = db_with_workspace
    add_gold(conn, "w", "What is OAuth?", ["oauth", "pkce"], ["raw/oauth_spec.md"])
    add_gold(conn, "w", "Token expiry?", ["expire", "token"], ["raw/oauth_spec.md"])

    answers = {
        "What is OAuth?": {
            "answer": "OAuth uses PKCE for public clients.",
            "sources": [{"path": "raw/oauth_spec.md"}],
        },
        "Token expiry?": {
            "answer": "Refresh tokens expire after 30 days.",
            "sources": [{"path": "raw/oauth_spec.md"}],
        },
    }
    result = run_benchmark(conn, "w", ws_dir, _scripted_runner(answers))
    assert result.sampled == 2
    assert result.skipped_no_llm == 0
    assert result.mean_citation_overlap == 1.0
    assert 0.0 < result.mean_topic_overlap <= 1.0


def test_run_benchmark_counts_skipped_when_runner_returns_none(db_with_workspace) -> None:
    conn, ws_dir = db_with_workspace
    add_gold(conn, "w", "Q1", ["x"], [])

    def silent_runner(*_args, **_kw):
        return None

    result = run_benchmark(conn, "w", ws_dir, silent_runner)
    assert result.sampled == 0
    assert result.skipped_no_llm == 1


# ---------- M6 metric integration ----------


def test_m6_no_gold_returns_score_one(db_with_workspace) -> None:
    conn, _ = db_with_workspace
    metric = M6RetroactiveQuery(runner=_scripted_runner({}))
    result = metric.compute(conn, "w")
    assert result.score == 1.0
    assert result.passed is True
    assert result.detail["sampled"] == 0


def test_m6_with_perfect_answers_passes_threshold(db_with_workspace) -> None:
    conn, _ = db_with_workspace
    add_gold(conn, "w", "Q", ["oauth", "pkce"], ["raw/oauth_spec.md"])
    answer = {
        "answer": "OAuth uses PKCE for clients [Source: raw/oauth_spec.md].",
        "sources": [{"path": "raw/oauth_spec.md"}],
    }
    metric = M6RetroactiveQuery(runner=_scripted_runner({"Q": answer}))
    result = metric.compute(conn, "w")
    assert result.detail["sampled"] == 1
    assert result.score > 0
    assert result.detail["mean_citation_overlap"] == 1.0


def test_m6_workspace_unknown(db_with_workspace) -> None:
    conn, _ = db_with_workspace
    metric = M6RetroactiveQuery(runner=_scripted_runner({}))
    result = metric.compute(conn, "missing")
    assert result.passed is False
    assert "error" in result.detail


def test_m6_no_runner_no_provider_reports_error(db_with_workspace, monkeypatch) -> None:
    """With no LLM provider configured, M6 returns a clear error rather than crashing."""
    conn, _ = db_with_workspace
    add_gold(conn, "w", "Q", ["a"], [])

    def no_provider():
        return None
    monkeypatch.setattr("alexandria.core.llm_ingest._get_provider", no_provider)

    metric = M6RetroactiveQuery()  # runner=None forces _default_runner path
    result = metric.compute(conn, "w")
    assert result.passed is False
    assert "no LLM" in result.detail["error"]
