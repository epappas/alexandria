"""Tests for the 0.37.3 worker reliability fixes:
single-worker lock, stale-job reclaim, heartbeat, mid-URL cancel.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alexandria.db.connection import connect, db_path
from alexandria.jobs.model import JobStatus
from alexandria.jobs.queue import (
    enqueue_ingest,
    get_job,
    list_jobs,
    update_status,
)
from alexandria.jobs.worker import (
    _acquire_lock,
    _reclaim_stale,
    _refresh_lock,
    _release_lock,
    worker_loop,
)


def test_acquire_lock_is_exclusive(initialized_home: Path) -> None:
    first = _acquire_lock(initialized_home)
    assert first is not None

    second = _acquire_lock(initialized_home)
    assert second is None  # cannot acquire while first holds it

    _release_lock(first)
    third = _acquire_lock(initialized_home)
    assert third is not None
    _release_lock(third)


def test_reclaim_returns_stale_running_jobs_to_queue(
    initialized_home: Path,
) -> None:
    # One fresh running (< stale cutoff), one stale (> cutoff)
    stale_ts = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    fresh_ts = datetime.now(UTC).isoformat()

    with connect(db_path(initialized_home)) as conn:
        stale_job = enqueue_ingest(conn, "global", {"source": "stale"})
        fresh_job = enqueue_ingest(conn, "global", {"source": "fresh"})
        conn.execute(
            """UPDATE jobs SET status = 'running', started_at = ?, updated_at = ?
               WHERE job_id = ?""",
            (stale_ts, stale_ts, stale_job.job_id),
        )
        conn.execute(
            """UPDATE jobs SET status = 'running', started_at = ?, updated_at = ?
               WHERE job_id = ?""",
            (fresh_ts, fresh_ts, fresh_job.job_id),
        )

    reclaimed = _reclaim_stale(initialized_home, stale_after_s=300)
    assert reclaimed == 1

    with connect(db_path(initialized_home)) as conn:
        stale_after = get_job(conn, stale_job.job_id)
        fresh_after = get_job(conn, fresh_job.job_id)

    assert stale_after.status == JobStatus.QUEUED
    assert stale_after.started_at == ""
    assert fresh_after.status == JobStatus.RUNNING  # untouched


def test_reclaim_handles_running_jobs_with_null_updated_at(
    initialized_home: Path,
) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
        conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = NULL "
            "WHERE job_id = ?",
            (job.job_id,),
        )
    reclaimed = _reclaim_stale(initialized_home, stale_after_s=60)
    assert reclaimed == 1


def test_worker_loop_refuses_to_start_when_locked(
    initialized_home: Path,
) -> None:
    lock = _acquire_lock(initialized_home)
    assert lock is not None
    try:
        stop = asyncio.Event()
        stop.set()  # even if it did start, it should exit immediately
        # Run with a wall-time budget; the loop should return because
        # the lock check fires first.
        asyncio.run(asyncio.wait_for(
            worker_loop(home=initialized_home, stop_event=stop),
            timeout=2.0,
        ))
    finally:
        _release_lock(lock)

    # No worker ran → queue untouched. Verify by claiming ourselves.
    with connect(db_path(initialized_home)) as conn:
        assert list_jobs(conn, workspace="global") == []


def test_heartbeat_touches_updated_at_during_long_ingest(
    initialized_home: Path,
) -> None:
    """The heartbeat task should bump updated_at even if the job body
    itself never calls update_progress."""
    from alexandria.jobs.worker import _run_with_heartbeat

    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "fake"})
        # simulate claim
        update_status(conn, job.job_id, JobStatus.RUNNING)
        before = get_job(conn, job.job_id)

    # Patch _run_job to sleep long enough to trigger at least one heartbeat.
    import alexandria.jobs.worker as worker_mod

    original = worker_mod._run_job

    def slow(home: Path, j, model: str) -> None:
        import time
        time.sleep(1.2)
        # Don't mark terminal — we want to observe updated_at only.

    worker_mod._run_job = slow  # type: ignore[assignment]
    try:
        asyncio.run(_run_with_heartbeat(
            initialized_home, job, model="haiku", heartbeat_s=0.3,
        ))
    finally:
        worker_mod._run_job = original  # type: ignore[assignment]

    with connect(db_path(initialized_home)) as conn:
        after = get_job(conn, job.job_id)

    assert after.updated_at
    assert after.updated_at > before.updated_at


def test_acquire_lock_steals_stale_lock(
    initialized_home: Path, monkeypatch,
) -> None:
    """A lock whose mtime is older than LOCK_STALE_S must be takeover-able
    even while the original fd is still open (i.e. the holder process is
    alive but its worker died). This is the May 7 / May 18 failure mode.
    """
    import alexandria.jobs.worker as worker_mod

    monkeypatch.setattr(worker_mod, "LOCK_STALE_S", 1.0)

    first = _acquire_lock(initialized_home)
    assert first is not None

    lock_path = initialized_home / "jobs.lock"
    backdated = time.time() - 5.0
    os.utime(lock_path, (backdated, backdated))

    second = _acquire_lock(initialized_home)
    assert second is not None, "stale lock must be stealable"

    assert lock_path.stat().st_mtime > backdated + 1
    _release_lock(second)
    _release_lock(first)


def test_acquire_lock_respects_freshly_refreshed_lock(
    initialized_home: Path, monkeypatch,
) -> None:
    """A lock that is being refreshed (fresh mtime) must NOT be stolen."""
    import alexandria.jobs.worker as worker_mod

    monkeypatch.setattr(worker_mod, "LOCK_STALE_S", 1.0)

    first = _acquire_lock(initialized_home)
    assert first is not None
    try:
        _refresh_lock(first)
        second = _acquire_lock(initialized_home)
        assert second is None, "fresh lock must not be stolen"
    finally:
        _release_lock(first)


def test_refresh_lock_advances_mtime(initialized_home: Path) -> None:
    """_refresh_lock(fd) must bump mtime even after the path is unlinked
    — confirming we are using futimes (fd-based), not utime (path-based).
    """
    fd = _acquire_lock(initialized_home)
    assert fd is not None
    try:
        lock_path = initialized_home / "jobs.lock"
        backdated = time.time() - 100.0
        os.utime(fd.fileno(), (backdated, backdated))
        assert lock_path.stat().st_mtime < backdated + 1

        lock_path.unlink()
        _refresh_lock(fd)
        # Path no longer exists — verify we wrote to the underlying fd by
        # stat'ing it directly.
        st = os.fstat(fd.fileno())
        assert st.st_mtime > backdated + 1
    finally:
        _release_lock(fd)


def test_worker_loop_periodic_reclaim_inside_running_session(
    initialized_home: Path, monkeypatch,
) -> None:
    """A 'running' row with stale updated_at must be reclaimed by the
    periodic tick inside an already-running worker loop — not just at
    startup. This is the in-flight job leak path.
    """
    import alexandria.jobs.worker as worker_mod

    monkeypatch.setattr(worker_mod, "RECLAIM_INTERVAL_S", 0.2)

    fresh_running_id = ""
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "stuck"})
        fresh_running_id = job.job_id
        # Mark running with a brand-new updated_at; the startup reclaim
        # will not touch it.
        conn.execute(
            """UPDATE jobs SET status = 'running',
               started_at = ?, updated_at = ?
               WHERE job_id = ?""",
            (datetime.now(UTC).isoformat(),
             datetime.now(UTC).isoformat(),
             fresh_running_id),
        )

    backdate_holder: dict[str, str] = {"ts": ""}

    async def _run_then_age_then_stop() -> None:
        stop = asyncio.Event()
        worker = asyncio.create_task(
            worker_loop(home=initialized_home, stop_event=stop),
        )
        await asyncio.sleep(0.4)
        stale_ts = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
        backdate_holder["ts"] = stale_ts
        with connect(db_path(initialized_home)) as conn:
            conn.execute(
                "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
                (stale_ts, fresh_running_id),
            )
        await asyncio.sleep(0.6)
        stop.set()
        await asyncio.wait_for(worker, timeout=3.0)

    asyncio.run(_run_then_age_then_stop())

    with connect(db_path(initialized_home)) as conn:
        final = get_job(conn, fresh_running_id)

    # The "stuck" state we're guarding against: status='running' with
    # the exact stale updated_at we backdated to. Any worker action
    # (reclaim → 'queued', subsequent claim → fresh updated_at,
    # processing → 'failed') breaks this conjunction.
    stuck = (
        final.status == JobStatus.RUNNING
        and final.updated_at == backdate_holder["ts"]
    )
    assert not stuck, (
        f"row left stuck: status={final.status}, "
        f"updated_at={final.updated_at} (= backdate value)"
    )


def test_should_cancel_short_circuits_url_ingest(
    initialized_home: Path, tmp_path: Path,
) -> None:
    """If the job is marked cancelled before the URL path runs, the
    worker should finalize as cancelled without attempting any I/O."""
    from alexandria.jobs.worker import _run_ingest

    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(
            conn, "global",
            {"source": "https://example.com/never-hit", "scope": "all"},
        )
        update_status(conn, job.job_id, JobStatus.CANCELLED)

    # Must not raise even though the URL is unreachable — the cancel
    # check short-circuits before fetch_and_save is invoked.
    _run_ingest(initialized_home, job, model="haiku")

    with connect(db_path(initialized_home)) as conn:
        final = get_job(conn, job.job_id)
    assert final.status == JobStatus.CANCELLED
