"""SQLite-backed job queue. Concurrency-safe via ``BEGIN IMMEDIATE``."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime

from alexandria.jobs.model import Job, JobStatus


class JobNotFoundError(Exception):
    """Raised when an operation targets a job that doesn't exist."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _job_id() -> str:
    """Monotonic-ish ID: date prefix + hash of (now, counter)."""
    seed = f"{time.time_ns()}"
    digest = hashlib.sha256(seed.encode()).hexdigest()[:12]
    return f"job-{datetime.now(UTC).strftime('%Y%m%d')}-{digest}"


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        workspace=row["workspace"],
        job_type=row["job_type"],
        spec=json.loads(row["spec"] or "{}"),
        status=JobStatus(row["status"]),
        files_total=row["files_total"],
        files_done=row["files_done"],
        files_failed=row["files_failed"],
        message=row["message"] or "",
        error=row["error"] or "",
        result=json.loads(row["result"] or "{}"),
        run_ids=json.loads(row["run_ids"] or "[]"),
        enqueued_at=row["enqueued_at"] or "",
        started_at=row["started_at"] or "",
        updated_at=row["updated_at"] or "",
        finished_at=row["finished_at"] or "",
    )


def enqueue_ingest(
    conn: sqlite3.Connection, workspace: str, spec: dict,
) -> Job:
    """Add an ingest job to the queue. Returns the created Job."""
    job_id = _job_id()
    now = _now_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO jobs
                 (job_id, workspace, job_type, spec, status,
                  enqueued_at, updated_at)
               VALUES (?, ?, 'ingest', ?, 'queued', ?, ?)""",
            (job_id, workspace, json.dumps(spec), now, now),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_job(conn, job_id)


def claim_next_queued(conn: sqlite3.Connection) -> Job | None:
    """Atomically claim the oldest queued job. Returns None if queue empty."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """SELECT * FROM jobs
               WHERE status = 'queued'
               ORDER BY enqueued_at
               LIMIT 1""",
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        now = _now_iso()
        conn.execute(
            """UPDATE jobs
               SET status = 'running', started_at = ?, updated_at = ?
               WHERE job_id = ? AND status = 'queued'""",
            (now, now, row["job_id"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return get_job(conn, row["job_id"])


def update_progress(
    conn: sqlite3.Connection, job_id: str, *,
    files_total: int | None = None,
    files_done: int | None = None,
    files_failed: int | None = None,
    message: str | None = None,
    run_ids: list[str] | None = None,
) -> None:
    """Update progress fields on an in-flight job."""
    updates = ["updated_at = ?"]
    params: list = [_now_iso()]
    if files_total is not None:
        updates.append("files_total = ?")
        params.append(files_total)
    if files_done is not None:
        updates.append("files_done = ?")
        params.append(files_done)
    if files_failed is not None:
        updates.append("files_failed = ?")
        params.append(files_failed)
    if message is not None:
        updates.append("message = ?")
        params.append(message[:500])
    if run_ids is not None:
        updates.append("run_ids = ?")
        params.append(json.dumps(run_ids))
    params.append(job_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?",
            tuple(params),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def update_status(
    conn: sqlite3.Connection, job_id: str, status: JobStatus, *,
    error: str = "", result: dict | None = None,
) -> None:
    """Transition a job to a new status, setting finished_at if terminal."""
    now = _now_iso()
    sql = "UPDATE jobs SET status = ?, updated_at = ?"
    params: list = [status.value, now]
    if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        sql += ", finished_at = ?"
        params.append(now)
    if error:
        sql += ", error = ?"
        params.append(error[:2000])
    if result is not None:
        sql += ", result = ?"
        params.append(json.dumps(result))
    sql += " WHERE job_id = ?"
    params.append(job_id)

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(sql, tuple(params))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel_job(conn: sqlite3.Connection, job_id: str) -> Job:
    """Mark a job as cancelled. The worker picks this up between files."""
    job = get_job(conn, job_id)
    if job.is_terminal:
        return job
    update_status(conn, job_id, JobStatus.CANCELLED,
                  error="cancelled by user request")
    return get_job(conn, job_id)


def get_job(conn: sqlite3.Connection, job_id: str) -> Job:
    """Return a Job or raise JobNotFoundError."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE job_id = ?", (job_id,),
    ).fetchone()
    if row is None:
        raise JobNotFoundError(job_id)
    return _row_to_job(row)


def list_jobs(
    conn: sqlite3.Connection, workspace: str | None = None,
    status: JobStatus | None = None, limit: int = 50,
) -> list[Job]:
    """Return recent jobs filtered by workspace/status, newest first."""
    clauses: list[str] = []
    params: list = []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if status:
        clauses.append("status = ?")
        params.append(status.value)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"""SELECT * FROM jobs {where}
            ORDER BY enqueued_at DESC LIMIT ?""",
        tuple(params),
    ).fetchall()
    return [_row_to_job(r) for r in rows]
