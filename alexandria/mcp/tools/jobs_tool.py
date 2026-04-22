"""MCP tools for the async job queue: jobs_list, jobs_status, jobs_cancel."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    @mcp.tool()
    def jobs_list(
        workspace: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> str:
        """List recent ingest jobs.

        Args:
            workspace: workspace slug (defaults to the pinned one).
            status: filter by status — queued | running | completed |
                failed | cancelled.
            limit: max rows returned (default 20).
        """
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.jobs.model import JobStatus
        from alexandria.jobs.queue import list_jobs

        _, slug = resolve(workspace)
        home = resolve_home()

        st = JobStatus(status) if status else None
        with connect(db_path(home)) as conn:
            jobs = list_jobs(conn, workspace=slug, status=st, limit=limit)

        if not jobs:
            return f"No jobs for workspace '{slug}'."

        lines = [f"{'ID':<28} {'STATUS':<10} {'PROGRESS':<14} MESSAGE"]
        for j in jobs:
            progress = f"{j.files_done}/{j.files_total}"
            lines.append(
                f"{j.job_id:<28} {j.status.value:<10} {progress:<14} "
                f"{(j.message or '')[:60]}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def jobs_status(job_id: str) -> str:
        """Full detail for one job: progress, ETA, error, committed pages."""

        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.jobs.queue import JobNotFoundError, get_job

        home = resolve_home()
        with connect(db_path(home)) as conn:
            try:
                job = get_job(conn, job_id)
            except JobNotFoundError:
                return f"No such job: {job_id}"

        lines = [
            f"Job:       {job.job_id}",
            f"Workspace: {job.workspace}",
            f"Status:    {job.status.value}",
            f"Source:    {job.spec.get('source', '')[:80]}",
            f"Scope:     {job.spec.get('scope', 'all')}",
            f"Progress:  {job.files_done}/{job.files_total} "
            f"({job.progress_pct}%)",
        ]
        if job.files_failed:
            lines.append(f"Failed:    {job.files_failed}")
        if job.message:
            lines.append(f"Message:   {job.message[:120]}")
        if job.error:
            lines.append(f"Error:     {job.error[:300]}")

        if job.started_at:
            lines.append(f"Started:   {job.started_at}")
            eta = _estimate_eta(job)
            if eta and not job.is_terminal:
                lines.append(f"ETA:       ~{eta}")
        if job.finished_at:
            lines.append(f"Finished:  {job.finished_at}")

        if job.run_ids:
            lines.append(
                f"\nCommitted ({len(job.run_ids)}): "
                f"{', '.join(job.run_ids[:10])}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def jobs_cancel(job_id: str) -> str:
        """Request cooperative cancellation of a running or queued job.

        Already-committed wiki pages stay in place; the worker stops
        after finishing the file it is currently processing.
        """
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.jobs.queue import JobNotFoundError, cancel_job

        home = resolve_home()
        with connect(db_path(home)) as conn:
            try:
                job = cancel_job(conn, job_id)
            except JobNotFoundError:
                return f"No such job: {job_id}"

        if job.is_terminal:
            return (
                f"Job {job_id} already in terminal state "
                f"({job.status.value}); no-op."
            )
        return f"Job {job_id} marked {job.status.value}."


def _estimate_eta(job: object) -> str:  # noqa: ANN001
    """Rough ETA from started_at + throughput so far."""
    from datetime import UTC, datetime

    if not job.started_at or job.files_total <= 0 or job.files_done <= 0:
        return ""
    try:
        started = datetime.fromisoformat(job.started_at)
    except ValueError:
        return ""
    elapsed = (datetime.now(UTC) - started).total_seconds()
    if elapsed <= 0:
        return ""
    rate = job.files_done / elapsed
    remaining = job.files_total - job.files_done
    if rate <= 0 or remaining <= 0:
        return ""
    eta_s = int(remaining / rate)
    if eta_s < 120:
        return f"{eta_s}s"
    if eta_s < 7200:
        return f"{eta_s // 60}m"
    return f"{eta_s // 3600}h{(eta_s % 3600) // 60}m"
