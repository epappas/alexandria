"""Evidence selection of the SJ mapping, on real files: a footnote defined twice on a merged or
hedged page, or one that quotes another source than the one an ingest publishes, never
becomes a citation. Needs sj-client installed, so it is marked ``sj``; it starts no sjd."""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.core.beliefs.model import Belief

pytestmark = pytest.mark.sj

PAGE = (
    "# Tides\n\nTides rise. [^1]\nTides fall. [^2]\n\n"
    '[^1]: raw/local/new.md — "New text says tides rise."\n'
    '[^1]: raw/local/old.md — "Old text says tides fall."\n'
    '[^2]: raw/local/old.md — "Old text says tides fall."\n'
)


def _workspace(tmp_path: Path) -> Path:
    raw = tmp_path / "ws" / "raw" / "local"
    raw.mkdir(parents=True)
    (raw / "new.md").write_text("New text says tides rise.\n", encoding="utf-8")
    (raw / "old.md").write_text("Old text says tides fall.\n", encoding="utf-8")
    return tmp_path / "ws"


def _beliefs() -> list[Belief]:
    return [
        Belief(statement="Tides rise.", topic="t", footnote_ids=["1"], wiki_document_path="wiki/t.md"),
        Belief(statement="Tides fall.", topic="t", footnote_ids=["2"], wiki_document_path="wiki/t.md"),
    ]


def test_an_ingest_cites_neither_a_repeated_footnote_nor_another_source(tmp_path: Path) -> None:
    from alexandria.core import sj_records as records

    workspace = _workspace(tmp_path)
    scope = records.Scope("default", "default", "w")
    only = workspace / "raw/local/new.md"
    plan = records.plan_claims(scope, workspace, PAGE, _beliefs(), only_source=only)
    assert plan.cited == []
    details = {item.detail for item in plan.unsupported if item.field == "evidence"}
    assert "footnote [^1] is defined more than once on the page, so its source is ambiguous" in details
    assert "footnote [^2] cites raw/local/old.md, not the source this ingest publishes" in details
    assert [item.field for item in plan.unsupported].count("claim") == 2


def test_a_belief_may_cite_an_existing_source_outside_an_ingest(tmp_path: Path) -> None:
    from alexandria.core import sj_records as records

    workspace = _workspace(tmp_path)
    scope = records.Scope("default", "default", "w")
    plan = records.plan_claims(scope, workspace, PAGE, _beliefs()[1:])
    [(belief, [quote])] = plan.cited
    old = (workspace / "raw/local/old.md").read_bytes()
    assert belief.statement == "Tides fall."
    assert quote.text == b"Old text says tides fall."
    assert quote.source_id == records.source_id(scope, "raw/local/old.md", old)
    assert not quote.ambiguous
