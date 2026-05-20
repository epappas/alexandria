"""Async job worker. Runs inside the MCP server process as a background
asyncio task; claims queued jobs, runs them in a thread (ingest is blocking
I/O + LLM), updates progress, emits heartbeats, reclaims stale jobs.

Single-worker-per-home is enforced by an fcntl flock on ``jobs.lock``
combined with an mtime heartbeat: the live holder bumps the lock file's
mtime every ``LOCK_REFRESH_S`` seconds, and a new acquirer treats a lock
older than ``LOCK_STALE_S`` as dead — it unlinks the file and retries,
which lets it take over even when the holder process is alive but its
worker coroutine has silently died.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alexandria.config import load_config, resolve_home
from alexandria.core.workspace import get_workspace
from alexandria.db.connection import connect, db_path
from alexandria.jobs.model import Job, JobStatus
from alexandria.jobs.queue import (
    JobNotFoundError,
    claim_next_queued,
    get_job,
    update_progress,
    update_status,
)

log = logging.getLogger(__name__)

LOCK_REFRESH_S = 10.0
LOCK_STALE_S = 60.0
RECLAIM_INTERVAL_S = 30.0


async def worker_loop(
    home: Path | None = None, stop_event: asyncio.Event | None = None,
) -> None:
    """Long-running worker. Polls the queue and runs jobs one at a time.

    Only one worker per ``home`` ever runs; additional callers exit
    immediately. Orphaned 'running' jobs are reclaimed back to 'queued'
    on startup. A background heartbeat task touches each in-progress
    job's ``updated_at`` every ``heartbeat_s`` seconds so stale
    detection works for future workers.

    The MCP server creates this as a background task and cancels it on
    shutdown. The loop exits when ``stop_event`` fires.
    """
    home = home or resolve_home()
    stop = stop_event or asyncio.Event()

    config = load_config(home)
    poll_s = config.jobs.poll_interval_s
    model = config.jobs.model
    heartbeat_s = config.jobs.heartbeat_s
    stale_after_s = config.jobs.stale_after_s

    lock = await asyncio.to_thread(_acquire_lock, home)
    if lock is None:
        log.info(
            "jobs worker not starting — another live worker holds "
            "%s/jobs.lock", home,
        )
        return

    bg_stop = asyncio.Event()
    refresh_task = asyncio.create_task(_lock_refresh_loop(lock, bg_stop))
    reclaim_task = asyncio.create_task(
        _reclaim_loop(home, stale_after_s, bg_stop),
    )

    try:
        reclaimed = await asyncio.to_thread(
            _reclaim_stale, home, stale_after_s,
        )
        if reclaimed:
            log.info("jobs worker reclaimed %d stale job(s) on startup",
                     reclaimed)
        log.info(
            "jobs worker started (model=%s, poll=%.1fs, heartbeat=%.0fs, "
            "stale_after=%ds)",
            model, poll_s, heartbeat_s, stale_after_s,
        )

        while not stop.is_set():
            if not db_path(home).exists():
                await asyncio.sleep(poll_s)
                continue

            job = await asyncio.to_thread(_claim_one, home)
            if job is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_s)
                except TimeoutError:
                    pass
                continue

            log.info("jobs worker picked up %s (%s)",
                     job.job_id, job.spec.get("source", "?"))
            await _run_with_heartbeat(home, job, model, heartbeat_s)

    finally:
        bg_stop.set()
        for t in (refresh_task, reclaim_task):
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        _release_lock(lock)
        log.info("jobs worker stopping")


# ---------------------------------------------------------------------------
# Lock + reclaim
# ---------------------------------------------------------------------------


def _acquire_lock(home: Path):
    """Try to acquire the per-home exclusive worker lock.

    Returns the open file object on success (caller owns it and must
    bump its mtime via ``_refresh_lock`` regularly), or None if a live
    worker already holds it.

    A lock is treated as stale — and forcibly taken over — when the
    file's mtime is older than ``LOCK_STALE_S``. fcntl arbitrates the
    actual hand-off: after we unlink the stale path, the next ``open``
    creates a fresh inode that only one racing acquirer can flock.
    """
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / "jobs.lock"
    for _ in range(3):
        fd = lock_path.open("a+")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < LOCK_STALE_S:
                return None
            log.warning(
                "jobs worker stealing stale lock (mtime age %.0fs > %.0fs)",
                age, LOCK_STALE_S,
            )
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            continue
        fd.seek(0)
        fd.truncate(0)
        fd.write(f"{os.getpid()}\n{int(time.time())}\n")
        fd.flush()
        return fd
    return None


def _refresh_lock(fd) -> None:  # noqa: ANN001
    """Bump the lock file's mtime via the open fd (POSIX futimes).

    Touching by fd, not path, survives the unlink race where another
    acquirer has already stolen this lock: our refresh lands on the
    unlinked inode and does not interfere with the new holder.
    """
    try:
        os.utime(fd.fileno(), None)
    except OSError as exc:
        log.debug("lock refresh failed: %s", exc)


async def _lock_refresh_loop(fd, stop: asyncio.Event) -> None:  # noqa: ANN001
    """Refresh the lock mtime every LOCK_REFRESH_S until ``stop`` fires."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=LOCK_REFRESH_S)
        except TimeoutError:
            pass
        if stop.is_set():
            return
        _refresh_lock(fd)


async def _reclaim_loop(
    home: Path, stale_after_s: int, stop: asyncio.Event,
) -> None:
    """Periodically reclaim in-flight 'running' rows whose heartbeat went
    stale. Runs as a sibling of the main poll loop so its cadence is
    independent of ``poll_interval_s``.
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=RECLAIM_INTERVAL_S)
        except TimeoutError:
            pass
        if stop.is_set():
            return
        try:
            r = await asyncio.to_thread(_reclaim_stale, home, stale_after_s)
            if r:
                log.info(
                    "jobs worker reclaimed %d stale job(s) mid-loop", r,
                )
        except Exception as exc:
            log.warning("periodic reclaim failed: %s", exc)


def _release_lock(fd) -> None:  # noqa: ANN001
    if fd is None:
        return
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fd.close()
    except Exception:
        pass


def _reclaim_stale(home: Path, stale_after_s: int) -> int:
    """Reset 'running' jobs with stale updated_at back to 'queued'.

    Called once at worker startup — we only reach this code path after
    acquiring the single-worker lock, so any 'running' jobs are from
    a previous worker that exited without marking them complete.
    """
    cutoff = (datetime.now(UTC) - timedelta(seconds=stale_after_s)).isoformat()
    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                """UPDATE jobs
                   SET status = 'queued', started_at = NULL
                   WHERE status = 'running'
                     AND (updated_at IS NULL OR updated_at < ?)""",
                (cutoff,),
            )
            reclaimed = cur.rowcount
            # Aggressively reset any 'running' with no updated_at at all
            # — these are from pre-heartbeat workers.
            cur = conn.execute(
                """UPDATE jobs
                   SET status = 'queued', started_at = NULL
                   WHERE status = 'running' AND updated_at IS NULL""",
            )
            reclaimed += cur.rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return reclaimed


def _claim_one(home: Path) -> Job | None:
    """Thread-safe queue claim."""
    with connect(db_path(home)) as conn:
        return claim_next_queued(conn)


# ---------------------------------------------------------------------------
# Job execution with heartbeat
# ---------------------------------------------------------------------------


async def _run_with_heartbeat(
    home: Path, job: Job, model: str, heartbeat_s: float,
) -> None:
    """Run the job in a thread; in parallel, refresh updated_at regularly."""
    stopped = asyncio.Event()

    async def _beat() -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=heartbeat_s)
            except TimeoutError:
                pass
            if stopped.is_set():
                return
            try:
                with connect(db_path(home)) as conn:
                    update_progress(conn, job.job_id)  # touches updated_at
            except Exception as exc:
                log.debug("heartbeat failed for %s: %s", job.job_id, exc)

    hb_task = asyncio.create_task(_beat())
    try:
        await asyncio.to_thread(_run_job, home, job, model)
    except Exception as exc:
        log.exception("jobs worker fatal on %s: %s", job.job_id, exc)
        try:
            with connect(db_path(home)) as conn:
                update_status(
                    conn, job.job_id, JobStatus.FAILED,
                    error=f"worker crash: {exc!r}",
                )
        except Exception:
            pass
    finally:
        stopped.set()
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass


def _run_job(home: Path, job: Job, model: str) -> None:
    """Dispatch by job_type. Today only ingest is supported."""
    if job.job_type != "ingest":
        with connect(db_path(home)) as conn:
            update_status(
                conn, job.job_id, JobStatus.FAILED,
                error=f"unknown job_type: {job.job_type}",
            )
        return
    _run_ingest(home, job, model)


def _run_ingest(home: Path, job: Job, model: str) -> None:
    """Execute an ingest job with per-stage messages and cancel checks.

    Pins ``ALEXANDRIA_CLAUDE_MODEL`` to the configured jobs model for
    the duration of the call so background ingest always uses Haiku
    regardless of the parent session.
    """
    from alexandria.core.ingest import IngestError, ingest_file
    from alexandria.core.repo_ingest import clone_repo, ingest_repo
    from alexandria.core.web import WebFetchError, fetch_and_save

    spec = job.spec
    source: str = spec["source"]
    topic = spec.get("topic")
    no_merge = bool(spec.get("no_merge", False))
    scope = spec.get("scope", "all")

    ws = get_workspace(home, job.workspace)
    ws_path = ws.path

    prior_model = os.environ.get("ALEXANDRIA_CLAUDE_MODEL")
    os.environ["ALEXANDRIA_CLAUDE_MODEL"] = model

    def should_cancel() -> bool:
        with connect(db_path(home)) as conn:
            try:
                cur = get_job(conn, job.job_id)
            except JobNotFoundError:
                return True
            return cur.status == JobStatus.CANCELLED

    def set_message(msg: str) -> None:
        with connect(db_path(home)) as conn:
            update_progress(conn, job.job_id, message=msg)

    def on_start(total: int) -> None:
        with connect(db_path(home)) as conn:
            update_progress(
                conn, job.job_id,
                files_total=total,
                message=f"starting: {total} files",
            )

    done_counter = {"ok": 0, "fail": 0}
    committed_paths: list[str] = []

    def on_file(rel: str, status: str) -> None:
        if status == "committed" or status == "skipped":
            done_counter["ok"] += 1
        else:
            done_counter["fail"] += 1
        with connect(db_path(home)) as conn:
            update_progress(
                conn, job.job_id,
                files_done=done_counter["ok"],
                files_failed=done_counter["fail"],
                message=f"{status}: {rel}",
            )

    try:
        result: dict = {}

        if _is_git_url(source):
            set_message(f"cloning {source}")
            repo_path = clone_repo(source, ws_path / "raw" / "git")
            if should_cancel():
                _finalize_cancelled(home, job.job_id, committed_paths)
                return
            rr = ingest_repo(
                home=home, workspace_slug=job.workspace,
                workspace_path=ws_path, repo_path=repo_path,
                topic=topic, on_progress=on_file, on_start=on_start,
                no_merge=no_merge, scope=scope,
                should_cancel=should_cancel,
            )
            committed_paths = list(rr.committed)
            result = {
                "committed": len(rr.committed),
                "skipped": len(rr.skipped),
                "rejected": len(rr.rejected),
                "errors": rr.errors[:10],
                "kind": "git_repo",
            }

        elif source.startswith(("http://", "https://")):
            if should_cancel():
                _finalize_cancelled(home, job.job_id, committed_paths)
                return
            with connect(db_path(home)) as conn:
                update_progress(
                    conn, job.job_id,
                    files_total=1, message=f"fetching {source}",
                )
            try:
                source_path = fetch_and_save(source, ws_path)
            except WebFetchError as exc:
                raise IngestError(f"fetch failed: {exc}") from exc
            if should_cancel():
                _finalize_cancelled(home, job.job_id, committed_paths)
                return
            set_message(f"extracting {source_path.name}")
            ir = ingest_file(
                home=home, workspace_slug=job.workspace,
                workspace_path=ws_path, source_file=source_path,
                topic=topic, no_merge=no_merge,
            )
            on_file(source_path.name,
                    "committed" if ir.committed else "rejected")
            committed_paths = list(ir.committed_paths)
            result = {"kind": "url", "committed": ir.committed_paths}

        else:
            local = Path(source).expanduser().resolve()
            if not local.exists():
                raise IngestError(f"not found: {source}")
            if local.is_dir():
                set_message(f"scanning {local}")
                rr = ingest_repo(
                    home=home, workspace_slug=job.workspace,
                    workspace_path=ws_path, repo_path=local,
                    topic=topic, on_progress=on_file, on_start=on_start,
                    no_merge=no_merge, scope=scope,
                    should_cancel=should_cancel,
                )
                committed_paths = list(rr.committed)
                result = {
                    "committed": len(rr.committed),
                    "skipped": len(rr.skipped),
                    "rejected": len(rr.rejected),
                    "errors": rr.errors[:10],
                    "kind": "directory",
                }
            else:
                if should_cancel():
                    _finalize_cancelled(home, job.job_id, committed_paths)
                    return
                with connect(db_path(home)) as conn:
                    update_progress(
                        conn, job.job_id,
                        files_total=1, message=f"extracting {local.name}",
                    )
                ir = ingest_file(
                    home=home, workspace_slug=job.workspace,
                    workspace_path=ws_path, source_file=local,
                    topic=topic, no_merge=no_merge,
                )
                on_file(local.name,
                        "committed" if ir.committed else "rejected")
                committed_paths = list(ir.committed_paths)
                result = {"kind": "file", "committed": ir.committed_paths}

        if should_cancel():
            _finalize_cancelled(home, job.job_id, committed_paths)
            return

        with connect(db_path(home)) as conn:
            update_progress(conn, job.job_id, run_ids=committed_paths[:50])
            update_status(
                conn, job.job_id, JobStatus.COMPLETED, result=result,
            )

    except IngestError as exc:
        with connect(db_path(home)) as conn:
            update_status(
                conn, job.job_id, JobStatus.FAILED, error=str(exc),
            )
    finally:
        if prior_model is None:
            os.environ.pop("ALEXANDRIA_CLAUDE_MODEL", None)
        else:
            os.environ["ALEXANDRIA_CLAUDE_MODEL"] = prior_model


def _finalize_cancelled(
    home: Path, job_id: str, committed_paths: list[str],
) -> None:
    with connect(db_path(home)) as conn:
        update_progress(conn, job_id, run_ids=committed_paths[:50])
        update_status(
            conn, job_id, JobStatus.CANCELLED,
            error="cancelled by user request",
            result={"committed_before_cancel": committed_paths[:50]},
        )


def _is_git_url(source: str) -> bool:
    if source.endswith(".git"):
        return True
    if source.startswith(("git@", "ssh://")):
        return True
    if "github.com" in source and "/tree/" not in source:
        parts = source.rstrip("/").split("/")
        if len(parts) >= 5 and parts[-2] and parts[-1]:
            return True
    return False
