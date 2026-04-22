"""Async job queue. Long-running ingests enqueue a job; a worker inside
the MCP server processes them serially with progress + cancellation."""

from alexandria.jobs.model import Job, JobStatus
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

__all__ = [
    "Job",
    "JobStatus",
    "JobNotFoundError",
    "cancel_job",
    "claim_next_queued",
    "enqueue_ingest",
    "get_job",
    "list_jobs",
    "update_progress",
    "update_status",
]
