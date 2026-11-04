"""Capture queue — serializes concurrent conversation captures.

Per-workspace serialization prevents races when multiple sessions
fire hooks simultaneously.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alexandria.core.capture.conversation import CaptureError, capture_conversation


def enqueue_capture(
    conn: sqlite3.Connection,
    session_id: str,
    workspace: str,
    client: str,
    transcript_path: str,
) -> bool:
    """Enqueue a capture. Returns True if new, False if already queued with same hash."""
    content_hash = _file_hash(Path(transcript_path))
    now = datetime.now(UTC).isoformat()

    # Check if already processed with same hash
    row = conn.execute(
        "SELECT status, last_content_hash FROM capture_queue WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if row:
        if row["status"] == "done" and row["last_content_hash"] == content_hash:
            return False  # already captured, unchanged
        # Re-queue: content changed or previous attempt failed
        conn.execute(
            """UPDATE capture_queue
            SET status = 'pending', last_content_hash = ?, enqueued_at = ?, error = NULL
            WHERE session_id = ?""",
            (content_hash, now, session_id),
        )
        return True

    conn.execute(
        """INSERT INTO capture_queue
          (session_id, workspace, client, transcript_path, status, enqueued_at, last_content_hash)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
        (session_id, workspace, client, transcript_path, now, content_hash),
    )
    return True


def process_capture_queue(
    conn: sqlite3.Connection,
    workspace_path: Path,
    *,
    home: Path,
    workspace: str,
) -> int:
    """Process the pending captures of `workspace` (whose files live in `workspace_path`).
    Returns count processed.

    With SJ configured in `home`, each captured file is published into SJ before it is
    registered; a failed publication marks the capture failed with its error.
    """
    rows = conn.execute(
        "SELECT * FROM capture_queue WHERE status = 'pending' AND workspace = ? "
        "ORDER BY enqueued_at",
        (workspace,),
    ).fetchall()

    processed = 0
    for row in rows:
        session_id = row["session_id"]
        now = datetime.now(UTC).isoformat()

        conn.execute(
            "UPDATE capture_queue SET status = 'processing', started_at = ? WHERE session_id = ?",
            (now, session_id),
        )

        try:
            result = capture_conversation(
                transcript_path=Path(row["transcript_path"]),
                workspace_path=workspace_path,
                client=row["client"],
                session_id=session_id,
            )
            _publish_capture(home, row["workspace"], workspace_path, result)

            conn.execute("BEGIN IMMEDIATE")
            try:
                # Register captured doc in documents table (enables FTS)
                _register_capture_doc(conn, row["workspace"], result)

                # Emit event
                _emit_capture_event(conn, row["workspace"], row["client"], session_id)

                conn.execute(
                    """UPDATE capture_queue
                    SET status = 'done', completed_at = ?, last_content_hash = ?
                    WHERE session_id = ?""",
                    (datetime.now(UTC).isoformat(), result["content_hash"], session_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            processed += 1
        except (CaptureError, Exception) as exc:
            conn.execute(
                "UPDATE capture_queue SET status = 'failed', error = ? WHERE session_id = ?",
                (str(exc), session_id),
            )

    return processed


def _publish_capture(
    home: Path, workspace: str, workspace_path: Path, result: dict[str, Any],
) -> None:
    """Publishes the captured transcript into SJ when configured; raises on failure."""
    from alexandria.core.sj_store import SourceFacts, publish_source
    from alexandria.core.source_kind import infer_source_kind, is_ai_authored

    path = Path(result["absolute_path"])
    rel = str(result["output_path"])
    facts = SourceFacts(
        kind=infer_source_kind(path, rel), ai_authored=is_ai_authored(path, rel),
        extracted_by_llm=False, original_pdf=False,
    )
    publish_source(home, workspace, workspace_path, path, facts)


def _register_capture_doc(
    conn: sqlite3.Connection, workspace: str, result: dict[str, Any],
) -> None:
    """Register captured markdown in documents table for FTS indexing."""
    md_path = Path(result["absolute_path"])
    if not md_path.exists():
        return
    content = md_path.read_text(encoding="utf-8")
    doc_id = f"doc-{hashlib.sha256(result['output_path'].encode()).hexdigest()[:12]}"
    conn.execute(
        """INSERT OR REPLACE INTO documents
          (id, workspace, layer, path, filename, file_type, content,
           content_hash, size_bytes, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (doc_id, workspace, "raw", result["output_path"], md_path.name, "md",
         content, result["content_hash"], len(content),
         f"Conversation {result['session_id'][:16]}"),
    )


def _emit_capture_event(
    conn: sqlite3.Connection, workspace: str, client: str, session_id: str,
) -> None:
    """Emit a conversation event to the events table."""
    from alexandria.core.adapters.base import FetchedItem
    from alexandria.core.adapters.events import insert_event

    item = FetchedItem(
        source_type="capture",
        event_type="conversation",
        title=f"Conversation {session_id[:16]}",
        author=client,
        occurred_at=datetime.now(UTC).isoformat(),
        event_data={"session_id": session_id, "client": client},
    )
    insert_event(conn, workspace, None, item)


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()
