"""Capture queue — serializes concurrent conversation captures.

Per-workspace serialization prevents races when multiple sessions
fire hooks simultaneously.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alexandria.core.capture.conversation import capture_conversation, CaptureError


def enqueue_capture(
    conn: sqlite3.Connection,
    session_id: str,
    workspace: str,
    client: str,
    transcript_path: str,
) -> bool:
    """Enqueue a capture. Returns True if new, False if already queued with same hash."""
    content_hash = _file_hash(Path(transcript_path))
    now = datetime.now(timezone.utc).isoformat()

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
) -> int:
    """Process all pending captures. Returns count processed."""
    rows = conn.execute(
        "SELECT * FROM capture_queue WHERE status = 'pending' ORDER BY enqueued_at"
    ).fetchall()

    processed = 0
    for row in rows:
        session_id = row["session_id"]
        now = datetime.now(timezone.utc).isoformat()

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
            conn.execute(
                """UPDATE capture_queue
                SET status = 'done', completed_at = ?, last_content_hash = ?
                WHERE session_id = ?""",
                (datetime.now(timezone.utc).isoformat(), result["content_hash"], session_id),
            )
            processed += 1
        except (CaptureError, Exception) as exc:
            conn.execute(
                "UPDATE capture_queue SET status = 'failed', error = ? WHERE session_id = ?",
                (str(exc), session_id),
            )

    return processed


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()
