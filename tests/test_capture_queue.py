"""Tests for capture queue."""

import json
from pathlib import Path

import pytest

from alexandria.core.capture.queue import enqueue_capture, process_capture_queue
from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator


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


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    lines = [
        json.dumps({"type": "human", "message": {"content": "Hello"}, "timestamp": "2025-01-15T10:00:00Z"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there!"}]}, "timestamp": "2025-01-15T10:00:05Z"}),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestEnqueueCapture:
    def test_enqueue_new(self, conn, transcript) -> None:
        result = enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        assert result is True

        row = conn.execute("SELECT * FROM capture_queue WHERE session_id = 'sess-1'").fetchone()
        assert row["status"] == "pending"

    def test_enqueue_duplicate_unchanged(self, conn, transcript) -> None:
        enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        # Mark as done
        conn.execute("UPDATE capture_queue SET status = 'done' WHERE session_id = 'sess-1'")
        # Re-enqueue with same content
        result = enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        assert result is False  # unchanged

    def test_enqueue_requeue_on_change(self, conn, transcript) -> None:
        enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        conn.execute("UPDATE capture_queue SET status = 'done' WHERE session_id = 'sess-1'")

        # Modify transcript
        transcript.write_text(transcript.read_text() + "\nnew content")
        result = enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        assert result is True  # re-queued


class TestProcessCaptureQueue:
    def test_process_pending(self, conn, transcript, tmp_path) -> None:
        workspace_path = tmp_path / "ws"
        workspace_path.mkdir()

        enqueue_capture(conn, "sess-1", "test", "claude-code", str(transcript))
        processed = process_capture_queue(conn, workspace_path)
        assert processed == 1

        row = conn.execute("SELECT * FROM capture_queue WHERE session_id = 'sess-1'").fetchone()
        assert row["status"] == "done"

    def test_process_handles_failure(self, conn, tmp_path) -> None:
        workspace_path = tmp_path / "ws"
        workspace_path.mkdir()

        # Enqueue with nonexistent transcript
        conn.execute(
            "INSERT INTO capture_queue (session_id, workspace, client, transcript_path, status, enqueued_at, last_content_hash) "
            "VALUES ('bad', 'test', 'claude-code', '/nonexistent', 'pending', '2025-01-01', '')"
        )
        processed = process_capture_queue(conn, workspace_path)
        assert processed == 0

        row = conn.execute("SELECT * FROM capture_queue WHERE session_id = 'bad'").fetchone()
        assert row["status"] == "failed"
        assert row["error"]
