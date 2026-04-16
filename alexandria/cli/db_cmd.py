"""``alexandria db`` group — migrate / status."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import resolve_home
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator, MigratorError

console = Console()


def migrate_command(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show pending migrations without applying them."
    ),
) -> None:
    """Apply pending schema migrations."""
    home = resolve_home()
    if not db_path(home).exists():
        console.print(
            "[yellow]No database yet.[/yellow] Run [cyan]alexandria init[/cyan] first."
        )
        raise typer.Exit(code=1)

    migrator = Migrator()
    with connect(db_path(home)) as conn:
        try:
            migrator.verify_no_tampering(conn)
        except MigratorError as exc:
            console.print(f"[red]Tampered migration detected:[/red] {exc}")
            raise typer.Exit(code=2) from exc

        pending = migrator.pending(conn)
        if not pending:
            console.print("[green]Schema is up to date.[/green]")
            console.print(f"[dim]Current version: {migrator.current_version(conn)}[/dim]")
            return

        if dry_run:
            console.print(f"[yellow]{len(pending)} pending migration(s):[/yellow]")
            for m in pending:
                console.print(f"  {m.version:04d}_{m.name} ({m.path.name})")
            console.print(
                "[dim]Run without --dry-run to apply.[/dim]"
            )
            return

        applied = migrator.apply_pending(conn)

    console.print(f"[green]Applied {len(applied)} migration(s):[/green]")
    for v in applied:
        console.print(f"  {v:04d}")


def status_command() -> None:
    """Show schema version and pending migrations."""
    home = resolve_home()
    if not db_path(home).exists():
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
        raise typer.Exit(code=1)

    migrator = Migrator()
    with connect(db_path(home)) as conn:
        current = migrator.current_version(conn)
        applied = migrator.applied_versions(conn)
        pending = migrator.pending(conn)
        try:
            migrator.verify_no_tampering(conn)
            tamper_status = "ok"
        except MigratorError as exc:
            tamper_status = f"TAMPERED — {exc}"

    console.print(f"[bold]Schema version:[/bold] {current}")
    console.print(f"[bold]Applied:[/bold] {len(applied)}")
    console.print(f"[bold]Pending:[/bold] {len(pending)}")
    console.print(f"[bold]Tamper check:[/bold] {tamper_status}")

    if applied:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Version")
        table.add_column("SHA256")
        for version, sha in sorted(applied.items()):
            table.add_row(str(version), sha[:16] + "…")
        console.print()
        console.print(table)
