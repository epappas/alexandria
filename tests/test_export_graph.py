"""Tests for the interactive belief-graph export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alexandria.core.export_graph import export_graph
from alexandria.core.workspace import GLOBAL_SLUG
from alexandria.db.connection import connect, db_path


def _insert_beliefs(conn, workspace: str) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """INSERT INTO wiki_beliefs
            (belief_id, workspace, topic, statement, wiki_document_path,
             source_kind, asserted_in_run, asserted_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("b-1", workspace, "research", "Long context degrades",
         "wiki/research/long-context.md", "paper", "run-1", now, now),
    )
    conn.execute(
        """INSERT INTO wiki_beliefs
            (belief_id, workspace, topic, statement, wiki_document_path,
             source_kind, asserted_in_run, asserted_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("b-2", workspace, "code", "Function foo() returns bar",
         "wiki/code/foo.md", "code", "run-2", now, now),
    )
    conn.execute("COMMIT")


def test_export_graph_emits_html_and_json(initialized_home: Path, tmp_path: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        _insert_beliefs(conn, GLOBAL_SLUG)
        result = export_graph(tmp_path / "graph-out", conn, GLOBAL_SLUG)

    assert (tmp_path / "graph-out" / "graph.json").exists()
    assert (tmp_path / "graph-out" / "graph.html").exists()

    payload = json.loads(
        (tmp_path / "graph-out" / "graph.json").read_text(encoding="utf-8"),
    )
    node_ids = {n["id"] for n in payload["nodes"]}
    assert "b-1" in node_ids
    assert "b-2" in node_ids
    # topic nodes added as well
    assert "topic:research" in node_ids
    assert "topic:code" in node_ids
    # Two in_topic edges expected (one per belief)
    in_topic = [e for e in payload["edges"] if e["relation"] == "in_topic"]
    assert len(in_topic) == 2

    assert result.nodes >= 4  # 2 beliefs + 2 topics

    html = (tmp_path / "graph-out" / "graph.html").read_text(encoding="utf-8")
    # Data is inlined, no CDN
    assert "__GRAPH_DATA__" not in html  # placeholder replaced
    assert "http://" not in html
    assert "cdn." not in html
    assert "unpkg." not in html
    # Canvas-based renderer is present
    assert "<canvas" in html
    assert '"b-1"' in html
