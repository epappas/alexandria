"""``alexandria beliefs`` group — list / history / verify / export."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.beliefs.repository import (
    dedup_current_beliefs,
    delete_orphaned_beliefs,
    get_belief,
    list_beliefs,
    verify_belief_anchors,
)
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def list_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    topic: Optional[str] = typer.Option(None, "--topic", help="Filter by topic."),
    current_only: bool = typer.Option(True, "--current/--all", help="Show only current beliefs."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List beliefs in the workspace."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    if not db_path(home).exists():
        console.print("[yellow]No database.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        beliefs = list_beliefs(conn, slug, topic=topic, current_only=current_only)

    if json_output:
        console.print_json(json.dumps([b.to_dict() for b in beliefs]))
        return

    if not beliefs:
        console.print(f"[yellow]No beliefs in {slug}.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", max_width=20)
    table.add_column("Statement", max_width=60)
    table.add_column("Topic")
    table.add_column("Asserted")
    table.add_column("Current")
    for b in beliefs:
        table.add_row(
            b.belief_id[:16] + "...",
            b.statement[:60],
            b.topic,
            b.asserted_at[:10],
            "yes" if b.is_current else f"no ({b.supersession_reason})",
        )
    console.print(table)


def history_command(
    belief_id: str = typer.Argument(..., help="Belief ID to trace."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the full supersession chain for a belief."""
    home = resolve_home()

    if not db_path(home).exists():
        console.print("[yellow]No database.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        chain: list = []
        current_id: str | None = belief_id
        visited: set[str] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            belief = get_belief(conn, current_id)
            if not belief:
                break
            chain.append(belief)
            current_id = belief.superseded_by_belief_id

    if json_output:
        console.print_json(json.dumps([b.to_dict() for b in chain]))
        return

    if not chain:
        console.print(f"[yellow]Belief {belief_id} not found.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Supersession chain for {belief_id}:[/bold]\n")
    for i, b in enumerate(chain):
        marker = "→ " if i < len(chain) - 1 else "  "
        status = "[green]current[/green]" if b.is_current else f"[dim]superseded ({b.supersession_reason})[/dim]"
        console.print(f"  {marker}[bold]{b.statement}[/bold]")
        console.print(f"    {status} | asserted {b.asserted_at[:10]}")
        if b.superseded_at:
            console.print(f"    superseded {b.superseded_at[:10]} by {b.superseded_by_belief_id}")
        console.print()


def verify_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Re-validate every belief's quote anchors against live raw sources."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        results = verify_belief_anchors(conn, ws.path, slug)

    if json_output:
        console.print_json(json.dumps([
            {"belief_id": r.belief_id, "verified": r.verified, "message": r.message}
            for r in results
        ]))
        return

    verified = sum(1 for r in results if r.verified)
    console.print(f"[bold]Belief verification:[/bold] {verified}/{len(results)} verified")
    for r in results:
        marker = "[green]OK[/green]" if r.verified else "[red]FAIL[/red]"
        console.print(f"  {marker} {r.belief_id[:16]}... — {r.message}")


def export_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    format: str = typer.Option("json", "--format", help="json or csv"),
) -> None:
    """Export beliefs to JSON or CSV."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    if not db_path(home).exists():
        console.print("[yellow]No database.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        beliefs = list_beliefs(conn, slug, current_only=False, limit=10_000)

    if format == "json":
        typer.echo(json.dumps([b.to_dict() for b in beliefs], indent=2))
    elif format == "csv":
        import csv
        import sys

        writer = csv.writer(sys.stdout)
        writer.writerow(["belief_id", "statement", "topic", "subject", "predicate", "object", "asserted_at", "superseded_at"])
        for b in beliefs:
            writer.writerow([b.belief_id, b.statement, b.topic, b.subject, b.predicate, b.object, b.asserted_at, b.superseded_at])


def cleanup_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without applying."),
) -> None:
    """Dedup beliefs and supersede orphans whose wiki pages no longer exist."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    from alexandria.core.workspace import get_workspace, WorkspaceNotFoundError
    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            deduped = dedup_current_beliefs(conn, slug)
            orphaned = delete_orphaned_beliefs(conn, slug, ws.path)

            if dry_run:
                conn.execute("ROLLBACK")
                console.print("[bold]Dry run:[/bold]")
            else:
                conn.execute("COMMIT")
                console.print("[bold]Cleanup complete:[/bold]")

            console.print(f"  Deduplicated: {deduped} belief(s)")
            console.print(f"  Orphaned:     {orphaned} belief(s)")
        except Exception:
            conn.execute("ROLLBACK")
            raise
