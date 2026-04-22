"""Job dataclass + status enum."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class Job:
    """In-memory representation of a queued job row."""

    job_id: str
    workspace: str
    job_type: str
    spec: dict
    status: JobStatus
    files_total: int = 0
    files_done: int = 0
    files_failed: int = 0
    message: str = ""
    error: str = ""
    result: dict = field(default_factory=dict)
    run_ids: list[str] = field(default_factory=list)
    enqueued_at: str = ""
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def progress_pct(self) -> float:
        if self.files_total <= 0:
            return 0.0
        return round((self.files_done / self.files_total) * 100, 1)
