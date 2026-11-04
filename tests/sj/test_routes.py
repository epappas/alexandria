"""query --save and conversation capture published into a real sjd through the same write
path, read back through SJ's query interface; positive and negative cases, nothing mocked.

The saved answer's text is handed to the save step directly: no model is called, and the test
makes no claim about what a model would answer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from alexandria.core.capture.queue import enqueue_capture, process_capture_queue
from alexandria.core.ingest import IngestResult
from alexandria.core.query_save import save_query_as_page
from alexandria.core.workspace import GLOBAL_SLUG
from alexandria.db.connection import connect as open_db
from alexandria.db.connection import db_path
from tests.sj import reads
from tests.sj.conftest import Connect, configure, sj_settings
from tests.sj.pki import Credentials
from tests.sj.test_writes import NOTE, _call, _documents, _free_port, _ingest, _workspace, _write

pytestmark = pytest.mark.sj

QUESTION = "How often do tides rise?"
SPOKEN = "Tides rise twice a day along the survey coast."


def _answer(*paths: str) -> dict[str, object]:
    return {"answer": "Twice a day.", "sources": [{"path": path, "title": path} for path in paths]}


def _save(home: Path, result: dict[str, object]) -> IngestResult:
    with open_db(db_path(home)) as conn:
        return save_query_as_page(home, GLOBAL_SLUG, _workspace(home), QUESTION, result, conn)


def test_query_save_publishes_the_page_and_links_the_raw_sources_sj_holds(
    sj_home: Path, connect: Connect, tmp_path: Path,
) -> None:
    _ingest(sj_home, _write(tmp_path / "note.md", NOTE))
    result = _answer("raw/local/note.md", "wiki/concepts/other.md", "raw/local/absent.md")
    saved = _save(sj_home, result)
    assert saved.committed and saved.sj is not None and saved.sj.snapshot == 2
    page_rel = f"wiki/{saved.committed_paths[0]}"
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    page = records.page_id(scope, page_rel)
    assert reads.resolve(client, page_rel) == [page]
    [link] = reads.links(client, page)
    assert link.link.target_id == records.document_id(scope, "raw/local/note.md")
    assert reads.entity_claims(client, page) == set()
    reported = {(item.field, item.detail) for item in saved.sj.unsupported}
    assert ("citation", "cites 'wiki/concepts/other.md'; only raw sources are linked") in reported
    assert ("citation", "cites raw/local/absent.md, which SJ does not hold; not linked") in reported
    assert {"page_content", "model/provider"} <= {field for field, _ in reported}
    again = _save(sj_home, result)
    assert again.sj is not None and (again.sj.replayed, again.sj.snapshot) == (True, 2)
    assert reads.version(client) == 2


def test_query_save_with_sj_down_saves_nothing(
    initialized_home: Path, credentials: Credentials, offline_cli: None,
) -> None:
    from alexandria.core.sj_store import SjUnavailable

    configure(initialized_home, sj_settings(f"127.0.0.1:{_free_port()}", credentials))
    with pytest.raises(SjUnavailable):
        _save(initialized_home, _answer())
    assert not list((_workspace(initialized_home) / "wiki").rglob("*tides*"))
    assert _documents(initialized_home) == []


def _transcript(tmp_path: Path) -> Path:
    lines = [
        {"type": "human", "message": {"content": SPOKEN}, "timestamp": "2026-01-15T10:00:00Z"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Noted."}]},
         "timestamp": "2026-01-15T10:00:05Z"},
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def _capture(home: Path, transcript: Path) -> tuple[int, str, str]:
    """Runs the capture queue once; returns how many were processed, the status and error."""
    with open_db(db_path(home)) as conn:
        enqueue_capture(conn, "sess-tides", GLOBAL_SLUG, "claude-code", str(transcript))
        processed = process_capture_queue(conn, _workspace(home), home=home)
        row = conn.execute(
            "SELECT status, error FROM capture_queue WHERE session_id = 'sess-tides'"
        ).fetchone()
    return processed, row["status"], row["error"] or ""


async def test_a_captured_conversation_is_published_with_its_exact_bytes(
    sj_home: Path, connect: Connect, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="alexandria.core.sj_store"):
        assert _capture(sj_home, _transcript(tmp_path)) == (1, "done", "")
    assert "speaker x1" in caplog.text and "source_kind x1" in caplog.text
    [captured] = list((_workspace(sj_home) / "raw/conversations/claude-code").glob("*.md"))
    rel = f"raw/conversations/claude-code/{captured.name}"
    data = captured.read_bytes()
    assert SPOKEN.encode() in data
    from alexandria.core import sj_records as records

    scope = reads.scope()
    client = connect("alexandria")
    assert reads.version(client) == 1
    assert reads.resolve(client, rel) == [records.document_id(scope, rel)]
    _write(
        _workspace(sj_home) / "wiki/concepts/capture.md",
        f'# Capture\n\nTides rise twice a day. [^1]\n\n[^1]: {rel} — "{SPOKEN}"\n',
    )
    added = await _call(
        "belief_add", statement="Tides rise twice a day.", topic="concepts",
        wiki_page="wiki/concepts/capture.md", footnote_ids="1",
    )
    [citation] = reads.explained_claim(client, records.claim_id(scope, added.split()[2])).citations
    assert citation.evidence.source_id == records.source_id(scope, rel, data)
    assert citation.content == SPOKEN.encode()


def test_a_capture_with_sj_down_fails_and_registers_nothing(
    initialized_home: Path, credentials: Credentials, offline_cli: None, tmp_path: Path,
) -> None:
    configure(initialized_home, sj_settings(f"127.0.0.1:{_free_port()}", credentials))
    processed, status, error = _capture(initialized_home, _transcript(tmp_path))
    assert (processed, status) == (0, "failed")
    assert error.startswith("SJ is unavailable")
    assert _documents(initialized_home) == []
