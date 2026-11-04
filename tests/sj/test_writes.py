"""Alexandria's knowledge writes published into a real sjd and read back through SJ's own query
interface: CLI ingest, the ingest pipeline the jobs worker runs, MCP belief_add and
belief_supersede, reindex and paste. Positive and negative cases; nothing is mocked."""

from __future__ import annotations

import hashlib
import socket
import time
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from alexandria.core.ingest import IngestResult, ingest_file
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace
from alexandria.db.connection import connect as open_db
from alexandria.db.connection import db_path
from alexandria.mcp.server import create_server
from tests.conftest import run_alexandria
from tests.sj import reads
from tests.sj.conftest import Connect, configure, sj_settings
from tests.sj.daemon import Daemon
from tests.sj.pki import Credentials

pytestmark = pytest.mark.sj

CODE = (
    '"""Tide tables for the field survey."""\n\n\n'
    "class TideTable:\n"
    '    """Predicted tides."""\n\n\n'
    "def predict(day):\n"
    "    return day\n"
)
CODE_QUOTE = b"Tide tables for the field survey."
NOTE = "# Tides\n\nTides rise twice a day along the survey coast.\nThe survey ran in May.\n"
NOTE_QUOTE = b"Tides rise twice a day along the survey coast."


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _workspace(home: Path) -> Path:
    return get_workspace(home, GLOBAL_SLUG).path


def _ingest(home: Path, source: Path) -> IngestResult:
    """The ingest pipeline the CLI, the jobs worker and MCP ingest all run."""
    return ingest_file(home, GLOBAL_SLUG, _workspace(home), source, no_merge=True)


def _current_beliefs(home: Path) -> dict[str, str]:
    with open_db(db_path(home)) as conn:
        rows = conn.execute(
            "SELECT belief_id, statement FROM wiki_beliefs WHERE superseded_at IS NULL"
        ).fetchall()
    return {row["belief_id"]: row["statement"] for row in rows}


def _documents(home: Path) -> list[str]:
    with open_db(db_path(home)) as conn:
        return [row["path"] for row in conn.execute("SELECT path FROM documents").fetchall()]


async def _call(name: str, **arguments: Any) -> str:
    """Calls an Alexandria MCP tool through FastMCP's tool dispatch."""
    server = create_server(pinned_workspace=GLOBAL_SLUG)
    result = await server.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(block, "text", "") for block in content)


def _added_id(text: str) -> str:
    """The belief id in belief_add's answer, `Belief added: <id> — ...`."""
    return text.split()[2]


def test_cli_ingest_publishes_the_source_page_link_and_cited_claims(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    source = _write(tmp_path / "tides.py", CODE)
    started = int(time.time())
    out = run_alexandria(sj_home, "ingest", str(source), "--no-merge").stdout
    finished = int(time.time()) + 1
    data = (_workspace(sj_home) / "raw/local/tides.py").read_bytes()
    assert data == CODE.encode()
    beliefs = _current_beliefs(sj_home)
    assert sorted(beliefs.values()) == ["Module defines TideTable", "Module defines predict(day)"]
    assert "SJ: committed 2 claim(s) at snapshot 1" in out
    assert "SJ did not carry:" in out
    [page_rel] = [path for path in _documents(sj_home) if path.startswith("wiki/")]
    scope = reads.scope()
    from alexandria.core import sj_records as records

    page = records.page_id(scope, page_rel)
    document = records.document_id(scope, "raw/local/tides.py")
    client = connect("alexandria")
    assert reads.version(client) == 1
    assert reads.entity_claims(client, page) == {records.claim_id(scope, b) for b in beliefs}
    for belief, statement in beliefs.items():
        response = reads.explain(client, records.claim_id(scope, belief))
        [item] = [entry.claim for entry in response.items]
        assert (item.subject_id, item.predicate) == (page, "states")
        assert item.object.literal.string == statement
        [citation] = item.citations
        assert citation.content == CODE_QUOTE
        assert citation.evidence.sha256 == hashlib.sha256(CODE_QUOTE).digest()
        assert citation.evidence.source_id == records.source_id(scope, "raw/local/tides.py", data)
        assert data[citation.evidence.span.start:citation.evidence.span.end] == CODE_QUOTE
        [cited] = response.explain.sources
        assert (cited.id, cited.sha256) == (citation.evidence.source_id, hashlib.sha256(data).digest())
        record = item.metadata.record
        assert record.valid_time.HasField("unknown")
        assert started <= record.observed_at.unix_seconds <= finished
    [link] = reads.links(client, page)
    assert link.WhichOneof("item") == "link"
    assert (link.link.id, link.link.target_id) == (
        records.link_id(scope, page_rel, "raw/local/tides.py"), document,
    )
    assert reads.resolve(client, page_rel) == [page]
    assert reads.resolve(client, "raw/local/tides.py") == [document]


def test_a_new_source_revision_is_a_new_source_and_earlier_claims_stay(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    source = _write(tmp_path / "tides.py", CODE)
    first = _ingest(sj_home, source)
    first_claims = set(first.sj.claims.values()) if first.sj else set()
    assert len(first_claims) == 2
    revised = CODE + "\n\ndef ebb(day):\n    return day\n"
    _write(source, revised)
    second = _ingest(sj_home, source)
    assert second.committed and second.sj is not None and second.sj.snapshot == 2
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    page = records.page_id(scope, f"wiki/{second.committed_paths[0]}")
    second_claims = set(second.sj.claims.values())
    assert len(second_claims) == 3 and not first_claims & second_claims
    assert reads.entity_claims(client, page) == first_claims | second_claims
    for claim in first_claims:
        assert not reads.explained_claim(client, claim).HasField("retraction")
    data = (_workspace(sj_home) / "raw/local/tides-2.py").read_bytes()
    assert data == revised.encode()
    for claim in second_claims:
        [citation] = reads.explained_claim(client, claim).citations
        assert citation.evidence.source_id == records.source_id(scope, "raw/local/tides-2.py", data)


async def test_mcp_belief_add_publishes_a_cited_claim_and_a_retry_writes_nothing(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    ingested = _ingest(sj_home, _write(tmp_path / "note.md", NOTE))
    assert ingested.sj is not None and ingested.sj.claims == {}
    page_rel = f"wiki/{ingested.committed_paths[0]}"
    client = connect("alexandria")
    assert reads.version(client) == 1
    arguments = {
        "statement": "Tides rise twice a day.", "topic": "concepts", "wiki_page": page_rel,
        "footnote_ids": "1", "subject": "tides", "predicate": "rise", "object": "twice a day",
    }
    first = await _call("belief_add", **arguments)
    assert "SJ: committed 1 claim(s) at snapshot 2" in first
    from alexandria.core import sj_records as records

    scope = reads.scope()
    claim = records.claim_id(scope, _added_id(first))
    item = reads.explained_claim(client, claim)
    assert item.object.literal.string == "Tides rise twice a day."
    assert [citation.content for citation in item.citations] == [NOTE_QUOTE]
    retry = await _call("belief_add", **arguments)
    assert _added_id(retry) == _added_id(first)
    assert "SJ: already committed 1 claim(s) at snapshot 2" in retry
    assert reads.version(client) == 2
    assert reads.entity_claims(client, records.page_id(scope, page_rel)) == {claim}
    assert list(_current_beliefs(sj_home).values()).count("Tides rise twice a day.") == 1


async def test_belief_supersede_publishes_a_retraction_and_the_replacement(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    page_rel = f"wiki/{_ingest(sj_home, _write(tmp_path / 'note.md', NOTE)).committed_paths[0]}"
    added = await _call(
        "belief_add", statement="Tides rise twice a day.", topic="concepts",
        wiki_page=page_rel, footnote_ids="1",
    )
    old = _added_id(added)
    reason = "the survey log says about twice a day"
    answer = await _call(
        "belief_supersede", belief_id=old, new_statement="Tides rise about twice a day.",
        reason=reason,
    )
    assert "SJ: committed 1 claim(s) at snapshot 3" in answer
    new = answer.split()[3]
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    withdrawn = reads.explained_claim(client, records.claim_id(scope, old))
    retraction = withdrawn.retraction.retraction
    assert retraction.claim_id == records.claim_id(scope, old)
    assert retraction.replacement_claim_id == records.claim_id(scope, new)
    assert retraction.reason == reason
    assert [c.content for c in withdrawn.retraction.citations] == [NOTE_QUOTE]
    replacement = reads.explained_claim(client, records.claim_id(scope, new))
    assert replacement.object.literal.string == "Tides rise about twice a day."
    assert [c.content for c in replacement.citations] == [NOTE_QUOTE]
    assert not replacement.HasField("retraction")
    with open_db(db_path(sj_home)) as conn:
        row = conn.execute(
            "SELECT superseded_by_belief_id FROM wiki_beliefs WHERE belief_id = ?", (old,)
        ).fetchone()
    assert row["superseded_by_belief_id"] == new


async def test_superseding_a_belief_sj_never_received_is_refused(
    sj_home: Path, sjd: Daemon, credentials: Credentials, connect: Connect, tmp_path: Path,
) -> None:
    page_rel = f"wiki/{_ingest(sj_home, _write(tmp_path / 'note.md', NOTE)).committed_paths[0]}"
    configure(sj_home, None)
    local_only = await _call(
        "belief_add", statement="Tides rise twice a day.", topic="concepts",
        wiki_page=page_rel, footnote_ids="1",
    )
    assert "SJ:" not in local_only
    configure(sj_home, sj_settings(sjd.address, credentials))
    old = _added_id(local_only)
    with pytest.raises(ToolError, match="ERROR_CODE_UNKNOWN_CLAIM"):
        await _call(
            "belief_supersede", belief_id=old, new_statement="Tides rise about twice a day.",
            reason="corrected",
        )
    assert reads.version(connect("alexandria")) == 1
    assert old in _current_beliefs(sj_home)


async def test_a_belief_without_a_verbatim_quote_gets_no_citation(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    page_rel = f"wiki/{_ingest(sj_home, _write(tmp_path / 'note.md', NOTE)).committed_paths[0]}"
    answer = await _call(
        "belief_add", statement="Tides matter to the survey.", topic="concepts", wiki_page=page_rel,
    )
    assert "SJ: nothing published" in answer
    assert "claim x1" in answer
    belief = _added_id(answer)
    assert _current_beliefs(sj_home)[belief] == "Tides matter to the survey."
    from sj_client import StoreError
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    assert reads.version(client) == 1
    with pytest.raises(StoreError) as missing:
        reads.explain(client, records.claim_id(scope, belief))
    assert missing.value.code == v3.ERROR_CODE_UNKNOWN_CLAIM
    page = records.page_id(scope, page_rel)
    assert reads.entity_claims(client, page) == set()
    [structural] = reads.links(client, page)
    assert structural.WhichOneof("item") == "link"


async def test_a_quote_the_source_does_not_hold_is_refused(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    _ingest(sj_home, _write(tmp_path / "note.md", NOTE))
    _write(
        _workspace(sj_home) / "wiki/concepts/forged.md",
        "# Forged\n\nTides are made of cheese. [^1]\n\n"
        '[^1]: raw/local/note.md — "Tides are made of cheese."\n',
    )
    with pytest.raises(ToolError, match="exact quote was not found"):
        await _call(
            "belief_add", statement="Tides are made of cheese.", topic="concepts",
            wiki_page="wiki/concepts/forged.md", footnote_ids="1",
        )
    from sj_client import StoreError
    from sj_client.v3 import store_pb2 as v3

    from alexandria.core import sj_records as records

    client = connect("alexandria")
    assert reads.version(client) == 1
    assert "Tides are made of cheese." not in _current_beliefs(sj_home).values()
    with pytest.raises(StoreError) as missing:
        reads.entity(client, records.page_id(reads.scope(), "wiki/concepts/forged.md"))
    assert missing.value.code == v3.ERROR_CODE_UNKNOWN_ENTITY


def test_fields_sj_cannot_carry_are_reported(sj_home: Path, tmp_path: Path) -> None:
    result = _ingest(sj_home, _write(tmp_path / "tides.py", CODE))
    assert result.committed and result.sj is not None
    reported = {(item.record, item.field): item.detail for item in result.sj.unsupported}
    for belief in _current_beliefs(sj_home):
        assert reported[(f"belief {belief}", "asserted_in_run")] == f"not carried ({result.run_id!r})"
        assert reported[(f"belief {belief}", "subject")].startswith("not carried (")
        for name in ("predicate", "object", "topic"):
            assert (f"belief {belief}", name) in reported
    source = "source raw/local/tides.py"
    assert reported[(source, "source_kind")] == "not carried ('code')"
    assert "is not carried" in reported[(source, "page_content")]
    assert (source, "ai_authored") not in reported


def test_a_namespace_the_principal_is_not_granted_is_refused_and_changes_nothing(
    initialized_home: Path, sjd: Daemon, credentials: Credentials, connect: Connect,
    offline_cli: None, tmp_path: Path,
) -> None:
    configure(initialized_home, sj_settings(sjd.address, credentials, tenant="other"))
    source = _write(tmp_path / "note.md", NOTE)
    failed = run_alexandria(initialized_home, "ingest", str(source), "--no-merge", expect_exit=2)
    assert "ERROR_CODE_NAMESPACE_NOT_GRANTED" in failed.stdout
    assert (
        "principal alexandria may not make call receipt: no data grant covers the selected "
        "namespace"
    ) in failed.stdout
    assert reads.version(connect("other"), tenant="other") == 0
    assert reads.version(connect("alexandria")) == 0
    assert _documents(initialized_home) == []
    assert not list((_workspace(initialized_home) / "wiki").rglob("note.md"))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


async def test_with_sj_configured_but_down_every_write_fails_loudly(
    initialized_home: Path, credentials: Credentials, offline_cli: None, tmp_path: Path,
) -> None:
    configure(initialized_home, sj_settings(f"127.0.0.1:{_free_port()}", credentials))
    source = _write(tmp_path / "note.md", NOTE)
    failed = run_alexandria(initialized_home, "ingest", str(source), "--no-merge", expect_exit=2)
    assert "SJ is unavailable" in failed.stdout
    assert _documents(initialized_home) == []
    workspace = _workspace(initialized_home)
    assert not list((workspace / "wiki").rglob("note.md"))
    _write(
        workspace / "wiki/concepts/tides.md",
        "# Tides\n\nTides rise twice a day. [^1]\n\n"
        '[^1]: raw/local/note.md — "Tides rise twice a day along the survey coast."\n',
    )
    with pytest.raises(ToolError, match="SJ is unavailable"):
        await _call(
            "belief_add", statement="Tides rise twice a day.", topic="concepts",
            wiki_page="wiki/concepts/tides.md", footnote_ids="1",
        )
    assert _current_beliefs(initialized_home) == {}


def test_reindex_and_paste_publish_through_the_same_write_path(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    page_rel = f"wiki/{_ingest(sj_home, _write(tmp_path / 'note.md', NOTE)).committed_paths[0]}"
    run_alexandria(sj_home, "reindex", "--rebuild-beliefs", "--workspace", GLOBAL_SLUG)
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    claims = reads.entity_claims(client, records.page_id(scope, page_rel))
    assert len(claims) == 1
    [claim] = claims
    item = reads.explained_claim(client, claim)
    assert item.object.literal.string == "The survey ran in May."
    assert [citation.content for citation in item.citations] == [NOTE_QUOTE]
    assert reads.version(client) == 2
    run_alexandria(sj_home, "reindex", "--rebuild-beliefs", "--workspace", GLOBAL_SLUG)
    assert reads.version(client) == 2
    assert reads.entity_claims(client, records.page_id(scope, page_rel)) == claims
    page_file = _workspace(sj_home) / page_rel
    page_file.write_text(page_file.read_text(encoding="utf-8") + "\nEdited by hand.\n", "utf-8")
    run_alexandria(sj_home, "reindex", "--rebuild-beliefs", "--workspace", GLOBAL_SLUG)
    assert reads.version(client) == 2
    assert reads.entity_claims(client, records.page_id(scope, page_rel)) == claims
    assert list(_current_beliefs(sj_home).values()).count("The survey ran in May.") == 1
    run_alexandria(sj_home, "paste", "--title", "Field log", "--content", "Boat left at dawn.")
    assert reads.version(client) == 3
    [pasted] = [p for p in _documents(sj_home) if p.startswith("/raw/local/")]
    [name] = [p.name for p in (_workspace(sj_home) / "raw/local").glob("*-field-log.md")]
    document = records.document_id(scope, f"raw/local/{name}")
    assert reads.resolve(client, f"raw/local/{name}") == [document]
    assert pasted == "/raw/local/"
