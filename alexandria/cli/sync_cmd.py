"""``alexandria sync`` — run source adapter sync cycles."""

from __future__ import annotations

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def sync_command(
    source_id: str | None = typer.Argument(None, help="Sync a specific source (by ID)."),
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Pull from configured sources.

    Runs sync for all enabled sources (or a specific one).
    Starts with an orphan sweep of stale source_runs.
    """
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
        raise typer.Exit(code=1)

    from alexandria.core.adapters.sync import run_sync
    from alexandria.core.circuit_breaker import CircuitBreakerRegistry
    from alexandria.core.ratelimit import RateLimitConfig, RateLimiter

    rate_limiter = RateLimiter()
    rate_limiter.register("github", RateLimitConfig(
        max_tokens=5000, refill_rate=5000 / 3600, name="github",
    ))
    circuit_breakers = CircuitBreakerRegistry()

    # Optionally set up secret resolver
    secret_resolver = None
    try:
        from alexandria.core.secrets.resolver import SecretResolver
        secret_resolver = SecretResolver(home)
    except Exception:
        pass

    with connect(db_path(home)) as conn:
        console.print("[dim]Starting sync...[/dim]")
        report = run_sync(
            conn=conn,
            home=home,
            workspace=slug,
            workspace_path=ws.path,
            source_id=source_id,
            rate_limiter=rate_limiter,
            circuit_breakers=circuit_breakers,
            secret_resolver=secret_resolver,
        )

        # Generate weekly self-report (amendment I6)
        from alexandria.core.adapters.report import generate_weekly_report
        try:
            report_path = generate_weekly_report(conn, home)
            console.print(f"[dim]Weekly report updated: {report_path}[/dim]")
        except Exception:
            pass  # non-critical

    console.print(
        f"\n[bold]Sync complete:[/bold] "
        f"{report.sources_succeeded}/{report.sources_attempted} sources, "
        f"{report.total_items} items, {report.total_errors} errors"
    )

    for ps in report.per_source:
        status_color = "green" if ps["status"] == "completed" else "red"
        console.print(
            f"  [{status_color}]{ps['name']}[/{status_color}]: "
            f"{ps.get('items_synced', 0)} synced, {ps.get('items_errored', 0)} errors"
        )
        for err in ps.get("errors", []):
            console.print(f"    [dim]{err}[/dim]")
