"""Tests for gold-query management (alexandria.eval.gold)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator
from alexandria.eval.gold import (
    GOLD_METRIC,
    add_gold,
    get_gold,
    list_gold,
    remove_gold,
)


@pytest.fixture
def conn(tmp_path: Path):
    with connect(tmp_path / "gold.db") as c:
        Migrator().apply_pending(c)
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES ('w', 'Test', ?, '2025-01-01', '2025-01-01')",
            (str(tmp_path / "ws"),),
        )
        c.execute("COMMIT")
        yield c


def test_add_returns_id_and_persists(conn) -> None:
    qid = add_gold(conn, "w", "What is OAuth?", ["oauth", "auth"], ["spec.md"])
    assert qid.startswith("gold-")
    fetched = get_gold(conn, qid)
    assert fetched is not None
    assert fetched.query == "What is OAuth?"
    assert fetched.expected_topics == ["oauth", "auth"]
    assert fetched.expected_citations == ["spec.md"]


def test_add_rejects_empty_query(conn) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        add_gold(conn, "w", "   ", ["x"], ["y"])


def test_add_rejects_no_expectations(conn) -> None:
    with pytest.raises(ValueError, match="expected_topics or expected_citations"):
        add_gold(conn, "w", "Q", [], [])


def test_add_strips_whitespace_in_lists(conn) -> None:
    qid = add_gold(conn, "w", "Q", ["  topic  ", "", "  "], ["  cite.md  "])
    fetched = get_gold(conn, qid)
    assert fetched is not None
    assert fetched.expected_topics == ["topic"]
    assert fetched.expected_citations == ["cite.md"]


def test_list_returns_only_workspace_entries_in_order(conn) -> None:
    qid_a = add_gold(conn, "w", "First", ["a"], [])
    qid_b = add_gold(conn, "w", "Second", ["b"], [])
    add_gold(conn, "w", "Other", ["c"], [])  # ensure list is not single-row

    rows = list_gold(conn, "w")
    assert [r.query_id for r in rows[:2]] == [qid_a, qid_b]


def test_list_filters_by_metric_tag(conn) -> None:
    """Entries written under a different metric tag must not appear."""
    qid = add_gold(conn, "w", "M6 entry", ["a"], [])
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO eval_gold_queries "
        "(query_id, workspace, query, expected, metric, created_at) "
        "VALUES ('foreign-1', 'w', 'M1 entry', '{}', 'M1', '2025-01-01')"
    )
    conn.execute("COMMIT")

    rows = list_gold(conn, "w")
    assert [r.query_id for r in rows] == [qid]
    assert all(GOLD_METRIC == "M6" for _ in rows)


def test_remove_returns_true_when_deleted(conn) -> None:
    qid = add_gold(conn, "w", "Q", ["a"], [])
    assert remove_gold(conn, qid) is True
    assert get_gold(conn, qid) is None


def test_remove_returns_false_when_missing(conn) -> None:
    assert remove_gold(conn, "gold-nonexistent") is False
