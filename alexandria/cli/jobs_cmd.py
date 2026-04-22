"""``alexandria jobs`` — inspect and control the async ingest queue."""

from __future__ import annotations

import time

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def list_command(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Filter by workspace.",
    ),
    status: str | None = typer.Option(
        None, "--status", "-s",
        help="queued | running | completed | failed | cancelled",
    ),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List recent ingest jobs."""
    from alexandria.jobs.model import JobStatus
    from alexandria.jobs.queue import list_jobs

    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    st = JobStatus(status) if status else None
    with connect(db_path(home)) as conn:
        jobs = list_jobs(conn, workspace=slug, status=st, limit=limit)

    if not jobs:
        console.print(f"[dim]No jobs for workspace '{slug}'.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Source", overflow="fold")
    table.add_column("Message", overflow="fold")

    for j in jobs:
        table.add_row(
            j.job_id,
            _status_color(j.status.value),
            f"{j.files_done}/{j.files_total}",
            (j.spec.get("source") or "")[:60],
            (j.message or "")[:60],
        )
    console.print(table)


def status_command(
    job_id: str = typer.Argument(..., help="Job ID to inspect."),
) -> None:
    """Show full detail for one job."""
    from alexandria.jobs.queue import JobNotFoundError, get_job

    home = resolve_home()
    with connect(db_path(home)) as conn:
        try:
            job = get_job(conn, job_id)
        except JobNotFoundError:
            console.print(f"[red]No such job:[/red] {job_id}")
            raise typer.Exit(code=1) from None

    console.print(f"[bold]{job.job_id}[/bold]")
    console.print(f"  Workspace: {job.workspace}")
    console.print(f"  Status:    {_status_color(job.status.value)}")
    console.print(f"  Source:    {job.spec.get('source', '')}")
    console.print(f"  Scope:     {job.spec.get('scope', 'all')}")
    console.print(
        f"  Progress:  {job.files_done}/{job.files_total} "
        f"({job.progress_pct}%)",
    )
    if job.files_failed:
        console.print(f"  Failed:    {job.files_failed}")
    if job.message:
        console.print(f"  Message:   {job.message}")
    if job.error:
        console.print(f"  [red]Error:     {job.error[:300]}[/red]")
    if job.started_at:
        console.print(f"  Started:   {job.started_at}")
    if job.finished_at:
        console.print(f"  Finished:  {job.finished_at}")
    if job.run_ids:
        console.print(
            f"\n  [green]Committed:[/green] {len(job.run_ids)} pages",
        )
        for p in job.run_ids[:10]:
            console.print(f"    • {p}")


def cancel_command(
    job_id: str = typer.Argument(..., help="Job ID to cancel."),
) -> None:
    """Request cooperative cancellation of a running or queued job."""
    from alexandria.jobs.queue import JobNotFoundError, cancel_job

    home = resolve_home()
    with connect(db_path(home)) as conn:
        try:
            job = cancel_job(conn, job_id)
        except JobNotFoundError:
            console.print(f"[red]No such job:[/red] {job_id}")
            raise typer.Exit(code=1) from None

    if job.is_terminal and job.status.value != "cancelled":
        console.print(
            f"[yellow]Job already terminal ({job.status.value}).[/yellow]",
        )
    else:
        console.print(f"[green]Cancel requested[/green] for {job.job_id}.")


def tail_command(
    job_id: str = typer.Argument(..., help="Job ID to follow."),
    interval: float = typer.Option(
        2.0, "--interval", help="Polling interval seconds.",
    ),
) -> None:
    """Stream a job's progress until it finishes. Ctrl+C to stop."""
    from alexandria.jobs.queue import JobNotFoundError, get_job

    home = resolve_home()
    last_done = -1
    last_msg = ""
    try:
        while True:
            with connect(db_path(home)) as conn:
                try:
                    job = get_job(conn, job_id)
                except JobNotFoundError:
                    console.print(f"[red]No such job:[/red] {job_id}")
                    raise typer.Exit(code=1) from None
            if job.files_done != last_done or job.message != last_msg:
                console.print(
                    f"[dim]{job.status.value}[/dim] "
                    f"{job.files_done}/{job.files_total}  "
                    f"{(job.message or '')[:80]}",
                )
                last_done = job.files_done
                last_msg = job.message
            if job.is_terminal:
                console.print(
                    f"[bold]{_status_color(job.status.value)}[/bold] "
                    f"— {(job.message or 'done')}",
                )
                return
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("[dim]stopped tailing; job continues running[/dim]")


def _status_color(status: str) -> str:
    colors = {
        "queued":    "[yellow]queued[/yellow]",
        "running":   "[cyan]running[/cyan]",
        "completed": "[green]completed[/green]",
        "failed":    "[red]failed[/red]",
        "cancelled": "[magenta]cancelled[/magenta]",
    }
    return colors.get(status, status)
