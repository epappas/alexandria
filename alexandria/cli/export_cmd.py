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
    format: str = typer.Option(
        "markdown", "--format", "-f",
        help="obsidian | markdown | json | github",
    ),
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Export wiki content to Obsidian, Markdown, JSON, or GitHub layout."""
    from pathlib import Path

    from alexandria.core.export import export_json, export_markdown, export_obsidian
    from alexandria.core.export_github import export_github

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
        files, out = result.files_exported, result.output_path
        fmt_label = result.format
    elif format == "obsidian":
        with connect(db_path(home)) as conn:
            result = export_obsidian(ws.path, output_dir, conn, slug)
        files, out = result.files_exported, result.output_path
        fmt_label = result.format
    elif format == "json":
        with connect(db_path(home)) as conn:
            result = export_json(ws.path, output_dir, conn, slug)
        files, out = result.files_exported, result.output_path
        fmt_label = result.format
    elif format == "github":
        with connect(db_path(home)) as conn:
            gh = export_github(ws.path, output_dir, conn, slug)
        files, out = gh.files_exported, gh.output_path
        fmt_label = (
            f"github ({gh.topics} topics, {gh.journal_months} journal months)"
        )
    else:
        console.print(f"[red]error:[/red] unknown format: {format}")
        console.print("[dim]Supported: obsidian, markdown, json, github[/dim]")
        raise typer.Exit(code=1)

    console.print(f"[green]Exported[/green] {files} files ({fmt_label})")
    console.print(f"  [cyan]{out}[/cyan]")
