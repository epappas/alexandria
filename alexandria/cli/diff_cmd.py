"""``alexandria diff`` — preview what changed since last ingest."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def diff_command(
    source: str = typer.Argument(..., help="File path to diff against last ingest."),
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
    full: bool = typer.Option(False, "--full", help="Show complete unified diff."),
) -> None:
    """Show what changed in a file since it was last ingested.

    Compares the current file content against the version stored in
    the database. Does not ingest — just previews the diff.
    """
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        console.print(f"[red]error:[/red] not found: {source}")
        raise typer.Exit(code=1)

    content = source_path.read_text(encoding="utf-8")

    if not db_path(home).exists():
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
        raise typer.Exit(code=1)

    import difflib
    import hashlib

    content_hash = hashlib.sha256(content.encode()).hexdigest()

    with connect(db_path(home)) as conn:
        # Find existing document by content hash or filename
        row = conn.execute(
            "SELECT content, content_hash, path, title FROM documents WHERE workspace = ? AND content_hash = ? LIMIT 1",
            (slug, content_hash),
        ).fetchone()

        if row:
            console.print("[dim]Unchanged (exact hash match)[/dim]")
            return

        # Search by filename
        row = conn.execute(
            "SELECT content, content_hash, path, title FROM documents WHERE workspace = ? AND filename = ? LIMIT 1",
            (slug, source_path.name),
        ).fetchone()

        if not row:
            console.print("[green]New file[/green] (not previously ingested)")
            return

        old_content = row["content"] or ""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = content.splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"wiki/{row['path']} (ingested)",
            tofile=str(source_path),
        ))

        if not diff:
            console.print("[dim]Unchanged[/dim]")
            return

        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        console.print(f"[bold]Changed:[/bold] [green]+{added}[/green] [red]-{removed}[/red] lines")

        if full:
            for line in diff:
                if line.startswith("+") and not line.startswith("+++"):
                    console.print(f"[green]{line.rstrip()}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(f"[red]{line.rstrip()}[/red]")
                elif line.startswith("@@"):
                    console.print(f"[cyan]{line.rstrip()}[/cyan]")
                else:
                    console.print(line.rstrip())
        else:
            # Show first 10 changed lines
            changes = [d for d in diff if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))]
            for line in changes[:10]:
                if line.startswith("+"):
                    console.print(f"  [green]{line.rstrip()}[/green]")
                else:
                    console.print(f"  [red]{line.rstrip()}[/red]")
            if len(changes) > 10:
                console.print(f"  [dim]... and {len(changes) - 10} more changes (use --full)[/dim]")
