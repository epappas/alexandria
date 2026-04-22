"""Tests for the async job queue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alexandria.db.connection import connect, db_path
from alexandria.jobs.model import JobStatus
from alexandria.jobs.queue import (
    JobNotFoundError,
    cancel_job,
    claim_next_queued,
    enqueue_ingest,
    get_job,
    list_jobs,
    update_progress,
    update_status,
)


def test_enqueue_stores_spec_and_returns_queued(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(
            conn, "global",
            {"source": "https://example.com/article", "scope": "all"},
        )
    assert job.status == JobStatus.QUEUED
    assert job.spec["source"] == "https://example.com/article"
    assert job.job_id.startswith("job-")
    assert job.files_total == 0


def test_claim_moves_queued_to_running(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        enqueue_ingest(conn, "global", {"source": "a"})
        enqueue_ingest(conn, "global", {"source": "b"})

        first = claim_next_queued(conn)
        second = claim_next_queued(conn)
        third = claim_next_queued(conn)

    assert first is not None and first.status == JobStatus.RUNNING
    assert second is not None and second.status == JobStatus.RUNNING
    assert third is None
    assert {first.spec["source"], second.spec["source"]} == {"a", "b"}


def test_update_progress_and_completion(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
        claim_next_queued(conn)
        update_progress(
            conn, job.job_id,
            files_total=10, files_done=3, message="processing 3/10",
        )
        update_status(
            conn, job.job_id, JobStatus.COMPLETED,
            result={"committed": 9, "rejected": 1},
        )
        final = get_job(conn, job.job_id)

    assert final.status == JobStatus.COMPLETED
    assert final.files_total == 10
    assert final.files_done == 3
    assert final.message == "processing 3/10"
    assert final.result == {"committed": 9, "rejected": 1}
    assert final.is_terminal
    assert final.finished_at


def test_cancel_running_job_marks_cancelled(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
        claim_next_queued(conn)
        cancelled = cancel_job(conn, job.job_id)
    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.error
    assert cancelled.is_terminal


def test_cancel_terminal_job_is_noop(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
        claim_next_queued(conn)
        update_status(conn, job.job_id, JobStatus.COMPLETED)
        cancelled = cancel_job(conn, job.job_id)
    assert cancelled.status == JobStatus.COMPLETED  # unchanged


def test_list_jobs_newest_first_and_filterable(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        j1 = enqueue_ingest(conn, "global", {"source": "a"})
        j2 = enqueue_ingest(conn, "global", {"source": "b"})
        claim_next_queued(conn)   # j1 -> running
        update_status(conn, j1.job_id, JobStatus.COMPLETED)

        all_jobs = list_jobs(conn, workspace="global")
        running_jobs = list_jobs(conn, workspace="global", status=JobStatus.QUEUED)
        done_jobs = list_jobs(
            conn, workspace="global", status=JobStatus.COMPLETED,
        )

    ids = [j.job_id for j in all_jobs]
    assert ids == [j2.job_id, j1.job_id]
    assert [j.job_id for j in running_jobs] == [j2.job_id]
    assert [j.job_id for j in done_jobs] == [j1.job_id]


def test_get_job_missing_raises(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        with pytest.raises(JobNotFoundError):
            get_job(conn, "nope")


def test_progress_pct_computed_safely(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
    assert job.progress_pct == 0.0
    with connect(db_path(initialized_home)) as conn:
        update_progress(conn, job.job_id, files_total=4, files_done=1)
        progress = get_job(conn, job.job_id)
    assert progress.progress_pct == 25.0


def test_run_ids_persist_as_json(initialized_home: Path) -> None:
    with connect(db_path(initialized_home)) as conn:
        job = enqueue_ingest(conn, "global", {"source": "x"})
        update_progress(conn, job.job_id, run_ids=["a/b.md", "c/d.md"])
        refreshed = get_job(conn, job.job_id)
    assert refreshed.run_ids == ["a/b.md", "c/d.md"]
