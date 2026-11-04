"""Retries and repeats against a real sjd. An ingest publishes the source version and the
compiled page as separate operations, so a retry that compiles another page (as a model's
extraction may) is published without a second Source, while the same page with other claims
is refused. A repeated write never brings a superseded belief back locally.

Where a test calls publish_ingest directly, the staged pages and beliefs it passes stand in
for two extraction attempts over one source; no model is called."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from alexandria.core.beliefs.model import Belief
from alexandria.core.workspace import GLOBAL_SLUG
from alexandria.db.connection import connect as open_db
from alexandria.db.connection import db_path
from tests.conftest import run_alexandria
from tests.sj import reads
from tests.sj.conftest import Connect
from tests.sj.helpers import (
    CODE,
    NOTE,
    added_id,
    call,
    current_beliefs,
    ingest,
    page_of,
    superseded_by,
    superseding_id,
    workspace,
    write,
)

if TYPE_CHECKING:
    from alexandria.core.sj_store import Publication

pytestmark = pytest.mark.sj

PAGE_REL = "wiki/concepts/tides.md"
QUOTED = "Tides rise twice a day along the survey coast."


def _page(tmp_path: Path, attempt: str, statement: str) -> Path:
    """A staged page as one extraction attempt compiles it."""
    text = f'# Tides\n\n{statement} [^1]\n\n[^1]: raw/local/tides.md — "{QUOTED}"\n'
    return write(tmp_path / attempt / "concepts" / "tides.md", text)


def _belief(statement: str) -> Belief:
    return Belief(
        workspace=GLOBAL_SLUG, statement=statement, topic="concepts",
        wiki_document_path=PAGE_REL, footnote_ids=["1"],
    )


def _publish(home: Path, raw: Path, page: Path, beliefs: list[Belief]) -> Publication | None:
    from alexandria.core.sj_store import SourceFacts, publish_ingest

    facts = SourceFacts(kind="manual", ai_authored=False, extracted_by_llm=True, original_pdf=False)
    return publish_ingest(home, GLOBAL_SLUG, workspace(home), raw, PAGE_REL, page, beliefs, facts)


def test_a_retry_that_compiles_another_page_is_published_without_a_second_source(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    raw = write(workspace(sj_home) / "raw/local/tides.md", NOTE)
    first = _publish(sj_home, raw, _page(tmp_path, "a", "Tides rise twice a day."),
                     [_belief("Tides rise twice a day.")])
    second = _publish(sj_home, raw, _page(tmp_path, "b", "Tides come in twice daily."),
                      [_belief("Tides come in twice daily.")])
    assert first is not None and second is not None
    assert (first.snapshot, second.snapshot) == (2, 3)
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    assert reads.version(client) == 3
    claims = set(first.claims.values()) | set(second.claims.values())
    assert len(claims) == 2
    assert reads.entity_claims(client, records.page_id(scope, PAGE_REL)) == claims
    source = records.source_id(scope, "raw/local/tides.md", raw.read_bytes())
    for claim in claims:
        [citation] = reads.explained_claim(client, claim).citations
        assert citation.evidence.source_id == source


def test_the_same_page_published_again_with_other_claims_is_refused(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    from alexandria.core.sj_store import SjWriteError

    raw = write(workspace(sj_home) / "raw/local/tides.md", NOTE)
    page = _page(tmp_path, "a", "Tides rise twice a day.")
    _publish(sj_home, raw, page, [_belief("Tides rise twice a day.")])
    with pytest.raises(SjWriteError, match="committed earlier with other content"):
        _publish(sj_home, raw, page, [_belief("Tides rise often.")])
    assert reads.version(connect("alexandria")) == 2


async def test_repeating_belief_add_after_a_supersede_keeps_it_superseded(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    page_rel = page_of(ingest(sj_home, write(tmp_path / "note.md", NOTE)))
    arguments = {
        "statement": "Tides rise twice a day.", "topic": "concepts", "wiki_page": page_rel,
        "footnote_ids": "1",
    }
    old = added_id(await call("belief_add", **arguments))
    new = superseding_id(await call(
        "belief_supersede", belief_id=old, new_statement="Tides rise about twice a day.",
        reason="corrected",
    ))
    again = await call("belief_add", **arguments)
    assert added_id(again) == old
    assert "SJ: already committed 1 claim(s) at snapshot 3" in again
    assert "Already recorded: the existing belief is kept as it is." in again
    assert superseded_by(sj_home, old) == new
    assert old not in current_beliefs(sj_home)
    from alexandria.core import sj_records as records

    client = connect("alexandria")
    assert reads.version(client) == 4
    withdrawn = reads.explained_claim(client, records.claim_id(reads.scope(), old))
    assert withdrawn.retraction.retraction.replacement_claim_id == records.claim_id(
        reads.scope(), new,
    )


async def test_rebuilding_from_the_sidecar_keeps_a_superseded_belief_superseded(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    ingest(sj_home, write(tmp_path / "note.md", NOTE))
    run_alexandria(sj_home, "reindex", "--rebuild-beliefs", "--workspace", GLOBAL_SLUG)
    [old] = [b for b, s in current_beliefs(sj_home).items() if s == "The survey ran in May."]
    new = superseding_id(await call(
        "belief_supersede", belief_id=old, new_statement="The survey ran in early May.",
        reason="corrected",
    ))
    run_alexandria(sj_home, "reindex", "--rebuild-beliefs", "--workspace", GLOBAL_SLUG)
    assert superseded_by(sj_home, old) == new
    assert "The survey ran in May." not in current_beliefs(sj_home).values()
    assert reads.version(connect("alexandria")) == 4


async def test_an_ingest_run_again_keeps_a_corrected_belief_superseded(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    source = write(tmp_path / "tides.py", CODE)
    first = ingest(sj_home, source)
    beliefs = current_beliefs(sj_home)
    [old] = [b for b, s in beliefs.items() if s == "Module defines TideTable"]
    [kept] = [b for b, s in beliefs.items() if s == "Module defines predict(day)"]
    new = superseding_id(await call(
        "belief_supersede", belief_id=old, new_statement="Module defines the TideTable class",
        reason="corrected",
    ))
    with open_db(db_path(sj_home)) as conn:  # the local index loses this ingest's record
        conn.execute("DELETE FROM documents WHERE workspace = ?", (GLOBAL_SLUG,))
    again = ingest(sj_home, source)
    assert again.committed and again.sj is not None and again.sj.replayed
    assert page_of(again) == page_of(first)
    assert superseded_by(sj_home, old) == new
    assert kept in current_beliefs(sj_home)
    assert reads.version(connect("alexandria")) == 3
