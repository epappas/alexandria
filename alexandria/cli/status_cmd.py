"""``alexandria status`` — operational dashboard (Phase 0 baseline)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from alexandria import __version__
from alexandria.config import config_path, load_config, resolve_home, resolve_workspace
from alexandria.core.fts_integrity import check_fts_integrity
from alexandria.core.workspace import list_workspaces
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator

console = Console()


def status_command(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of human output."),
) -> None:
    """Print a Phase-0 status snapshot.

    Shows the version, alexandria home, daemon state (always ``not running`` in
    Phase 0), schema version, workspace count + current workspace, and the
    FTS5 integrity result. Later phases extend this with adapter health,
    eval scores, run state, and more.
    """
    home = resolve_home()
    config = load_config(home)
    home_exists = home.exists()
    config_exists = config_path(home).exists()
    workspaces = list_workspaces(home) if db_path(home).exists() else []
    current = resolve_workspace(config) if config_exists else None

    schema_version, fts_status, fts_message = _read_db_state(home)

    if json_output:
        payload = {
            "version": __version__,
            "home": str(home),
            "home_exists": home_exists,
            "initialized": config_exists,
            "schema_version": schema_version,
            "current_workspace": current,
            "workspaces": [{"slug": w.slug, "name": w.name} for w in workspaces],
            "daemon": {"state": "not running", "phase_available": 6},
            "fts_integrity": {"status": fts_status, "message": fts_message},
            "phase": 0,
        }
        console.print_json(json.dumps(payload))
        return

    console.print(f"[bold]alexandria[/bold] [cyan]{__version__}[/cyan]")
    console.print()

    if not home_exists:
        console.print("[yellow]Not initialized.[/yellow] Run [cyan]alexandria init[/cyan].")
        console.print(f"[dim]Expected home: {home}[/dim]")
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Home", str(home))
    table.add_row("Initialized", "yes" if config_exists else "no")
    table.add_row("Schema version", str(schema_version))
    table.add_row("Current workspace", current or "(unset)")
    table.add_row("Workspaces", str(len(workspaces)))
    table.add_row(
        "Daemon",
        "[dim]not running (start with: alexandria daemon start — Phase 6)[/dim]",
    )
    fts_label = (
        f"[green]{fts_status}[/green]"
        if fts_status == "ok"
        else f"[red]{fts_status}[/red]"
    )
    if fts_message and fts_status != "ok":
        fts_label += f" — {fts_message}"
    table.add_row("FTS integrity", fts_label)
    console.print(table)

    if workspaces:
        console.print()
        console.print("[bold]Workspaces:[/bold]")
        for w in workspaces:
            marker = "→ " if w.slug == current else "  "
            console.print(f"  {marker}[cyan]{w.slug}[/cyan] — {w.name}")


def _read_db_state(home: Path) -> tuple[int, str, str | None]:
    """Return (schema_version, fts_status, fts_message)."""
    if not db_path(home).exists():
        return 0, "no_database", None
    with connect(db_path(home)) as conn:
        version = Migrator().current_version(conn)
        report = check_fts_integrity(conn)
    return version, report.status, report.error_message
