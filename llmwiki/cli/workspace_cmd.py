"""``llmwiki workspace`` group — use, current, list."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from llmwiki.config import (
    Config,
    StateConfig,
    load_config,
    resolve_home,
    resolve_workspace,
    save_config,
)
from llmwiki.core.workspace import (
    WorkspaceNotFoundError,
    get_workspace,
    list_workspaces,
)

console = Console()


def use_command(
    slug: str = typer.Argument(..., help="The workspace slug to switch to."),
) -> None:
    """Set the current workspace in the persistent config."""
    home = resolve_home()
    config = load_config(home)
    try:
        workspace = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    new_config = Config(
        general=config.general,
        state=StateConfig(current_workspace=workspace.slug),
        daemon=config.daemon,
        limits=config.limits,
        secrets=config.secrets,
    )
    save_config(home, new_config)
    console.print(
        f"[green]Current workspace set to[/green] [bold]{workspace.slug}[/bold] "
        f"({workspace.name})"
    )


def current_command(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Print the current workspace slug."""
    home = resolve_home()
    config = load_config(home)
    slug = resolve_workspace(config)
    if json_output:
        console.print_json(json.dumps({"current_workspace": slug, "home": str(home)}))
        return
    console.print(slug)


def list_command(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List all registered workspaces."""
    home = resolve_home()
    workspaces = list_workspaces(home)
    if json_output:
        payload = [
            {
                "slug": w.slug,
                "name": w.name,
                "description": w.description,
                "path": str(w.path),
                "contract_version": w.contract_version,
                "created_at": w.created_at,
                "updated_at": w.updated_at,
            }
            for w in workspaces
        ]
        console.print_json(json.dumps(payload))
        return

    if not workspaces:
        console.print(
            "[yellow]No workspaces found.[/yellow] Run [cyan]llmwiki init[/cyan] first."
        )
        return

    cfg = load_config(home)
    current = resolve_workspace(cfg)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Slug")
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Created")
    for w in workspaces:
        marker = "[green]→[/green] " if w.slug == current else "  "
        table.add_row(
            f"{marker}{w.slug}",
            w.name,
            str(w.path),
            w.created_at[:10],
        )
    console.print(table)
