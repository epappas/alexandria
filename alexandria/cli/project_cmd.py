"""``alexandria project`` group — create / list / info / rename / delete."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import resolve_home
from alexandria.core.workspace import (
    GLOBAL_SLUG,
    InvalidSlugError,
    WorkspaceError,
    WorkspaceExistsError,
    WorkspaceNotFoundError,
    delete_workspace,
    get_workspace,
    init_workspace,
    list_workspaces,
    rename_workspace,
)

console = Console()


def create_command(
    name: str = typer.Argument(..., help="Workspace name (also used as slug)."),
    slug: str | None = typer.Option(
        None, "--slug", help="Override the slug derived from the name."
    ),
    description: str | None = typer.Option(
        None, "--description", "-d", help="Short workspace description."
    ),
) -> None:
    """Create a new project workspace."""
    home = resolve_home()
    target_slug = slug or _slugify(name)
    try:
        workspace = init_workspace(home, slug=target_slug, name=name, description=description)
    except InvalidSlugError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except WorkspaceExistsError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Created workspace[/green] [bold]{workspace.slug}[/bold] "
        f"at {workspace.path}"
    )


def list_command(
    include_global: bool = typer.Option(
        True, "--global/--no-global", help="Include the 'global' workspace."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List project workspaces."""
    home = resolve_home()
    workspaces = list_workspaces(home)
    if not include_global:
        workspaces = [w for w in workspaces if w.slug != GLOBAL_SLUG]

    if json_output:
        payload = [
            {"slug": w.slug, "name": w.name, "path": str(w.path)} for w in workspaces
        ]
        console.print_json(json.dumps(payload))
        return

    if not workspaces:
        console.print("[yellow]No projects.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Slug")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Created")
    for w in workspaces:
        table.add_row(w.slug, w.name, w.description or "", w.created_at[:10])
    console.print(table)


def info_command(
    slug: str = typer.Argument(..., help="Workspace slug to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show details about a workspace."""
    home = resolve_home()
    try:
        workspace = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    raw_files = (
        sum(1 for _ in workspace.raw_dir.rglob("*") if _.is_file())
        if workspace.raw_dir.exists()
        else 0
    )
    wiki_files = (
        sum(1 for _ in workspace.wiki_dir.rglob("*") if _.is_file())
        if workspace.wiki_dir.exists()
        else 0
    )

    if json_output:
        console.print_json(
            json.dumps(
                {
                    "slug": workspace.slug,
                    "name": workspace.name,
                    "description": workspace.description,
                    "path": str(workspace.path),
                    "contract_version": workspace.contract_version,
                    "created_at": workspace.created_at,
                    "updated_at": workspace.updated_at,
                    "raw_files": raw_files,
                    "wiki_files": wiki_files,
                }
            )
        )
        return

    console.print(f"[bold]{workspace.name}[/bold] ([cyan]{workspace.slug}[/cyan])")
    if workspace.description:
        console.print(f"  {workspace.description}")
    console.print(f"  Path:        {workspace.path}")
    console.print(f"  Created:     {workspace.created_at}")
    console.print(f"  Contract:    {workspace.contract_version}")
    console.print(f"  Raw files:   {raw_files}")
    console.print(f"  Wiki files:  {wiki_files}")


def rename_command(
    old: str = typer.Argument(..., help="Existing slug."),
    new: str = typer.Argument(..., help="New slug."),
) -> None:
    """Rename a workspace's slug."""
    home = resolve_home()
    try:
        workspace = rename_workspace(home, old, new)
    except (WorkspaceNotFoundError, WorkspaceExistsError, WorkspaceError, InvalidSlugError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Renamed[/green] {old} → {workspace.slug}")


def delete_command(
    slug: str = typer.Argument(..., help="Workspace slug to delete."),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Soft-delete a workspace by moving it to the trash directory."""
    home = resolve_home()
    if not yes:
        confirm = typer.confirm(
            f"Move workspace {slug!r} to .trash/? This is reversible until gc."
        )
        if not confirm:
            raise typer.Exit(code=1)
    try:
        target = delete_workspace(home, slug)
    except (WorkspaceNotFoundError, WorkspaceError, InvalidSlugError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[yellow]Moved {slug} →[/yellow] {target}")


def _slugify(name: str) -> str:
    """Best-effort slug derivation: lowercase, hyphens, ASCII only."""
    out = []
    for char in name.strip().lower():
        if char.isalnum():
            out.append(char)
        elif char in (" ", "-", "_"):
            out.append("-")
    slug = "".join(out).strip("-")
    return slug or "workspace"
