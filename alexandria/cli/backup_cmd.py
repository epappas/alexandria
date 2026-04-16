"""``alexandria backup`` group — create (restore arrives in Phase 11)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from alexandria.config import resolve_home
from alexandria.core.backup import BackupError, create_backup

console = Console()


def create_command(
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination archive path (default: ~/.alexandria/backups/alexandria-backup-<ts>.tar.gz).",
    ),
) -> None:
    """Create an atomic backup tarball of the alexandria home."""
    home = resolve_home()
    try:
        report = create_backup(home, output)
    except BackupError as exc:
        console.print(f"[red]Backup failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"[green]Backup created[/green] [bold]{report.archive_path}[/bold]")
    console.print(f"[dim]Size:           {_human_size(report.size_bytes)}[/dim]")
    console.print(f"[dim]Files included: {report.files_included}[/dim]")
    console.print(f"[dim]DB snapshot:    {report.db_snapshot_path}[/dim]")


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"
