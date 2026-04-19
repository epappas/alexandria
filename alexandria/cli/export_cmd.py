"""``alexandria export`` — export wiki to Obsidian, Markdown, or JSON."""

from __future__ import annotations

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def export_command(
    output: str = typer.Argument(..., help="Output directory."),
    format: str = typer.Option("markdown", "--format", "-f", help="obsidian | markdown | json"),
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Export wiki content to Obsidian, Markdown, or JSON bundle."""
    from pathlib import Path

    from alexandria.core.export import export_json, export_markdown, export_obsidian

    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    output_dir = Path(output).expanduser().resolve()

    if format == "markdown":
        result = export_markdown(ws.path, output_dir)
    elif format == "obsidian":
        with connect(db_path(home)) as conn:
            result = export_obsidian(ws.path, output_dir, conn, slug)
    elif format == "json":
        with connect(db_path(home)) as conn:
            result = export_json(ws.path, output_dir, conn, slug)
    else:
        console.print(f"[red]error:[/red] unknown format: {format}")
        console.print("[dim]Supported: obsidian, markdown, json[/dim]")
        raise typer.Exit(code=1)

    console.print(f"[green]Exported[/green] {result.files_exported} files ({result.format})")
    console.print(f"  [cyan]{result.output_path}[/cyan]")
