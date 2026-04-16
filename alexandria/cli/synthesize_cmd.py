"""``alexandria synthesize`` — run temporal synthesis."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import get_workspace, WorkspaceNotFoundError
from alexandria.db.connection import connect, db_path

console = Console()


def synthesize_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    period: int = typer.Option(7, "--period", help="Period in days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing."),
    force: bool = typer.Option(False, "--force", help="Skip eval gate check."),
) -> None:
    """Generate a temporal synthesis digest from recent activity."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    from alexandria.core.synthesis import run_synthesis

    with connect(db_path(home)) as conn:
        # Check synthesis gate (M1/M2 health)
        if not force and not dry_run:
            from alexandria.eval.runner import check_synthesis_gate
            allowed, reasons = check_synthesis_gate(conn, slug)
            if not allowed:
                console.print("[red]Synthesis blocked by eval gate:[/red]")
                for r in reasons:
                    console.print(f"  [yellow]{r}[/yellow]")
                console.print("[dim]Use --force to override.[/dim]")
                raise typer.Exit(code=1)

        result = run_synthesis(conn, slug, ws.path, period_days=period, dry_run=dry_run)

    if result["status"] == "skipped":
        console.print(f"[yellow]Skipped:[/yellow] {result.get('reason', 'no activity')}")
    elif result["status"] == "dry_run":
        console.print("[bold]Dry run preview:[/bold]")
        console.print(result.get("content_preview", ""))
    else:
        console.print(
            f"[green]Synthesis complete:[/green] {result.get('output_path', '')}"
        )
        console.print(
            f"  {result.get('events_count', 0)} events, "
            f"{result.get('beliefs_count', 0)} beliefs, "
            f"{result.get('subscriptions_count', 0)} subscriptions"
        )
