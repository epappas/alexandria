"""``llmwiki source`` — manage configured source adapters."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from llmwiki.config import load_config, resolve_home, resolve_workspace
from llmwiki.core.workspace import get_workspace, WorkspaceNotFoundError
from llmwiki.db.connection import connect, db_path

console = Console()

VALID_TYPES = ("local", "git-local", "github")


def source_add_command(
    adapter_type: str = typer.Argument(..., help="Adapter type: local | git-local | github"),
    name: str = typer.Option(..., "--name", "-n", help="Human-readable name for this source."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    path: Optional[str] = typer.Option(None, "--path", help="Local directory path (for 'local' adapter)."),
    repo_url: Optional[str] = typer.Option(None, "--repo-url", help="Git repo URL (for 'git-local' adapter)."),
    owner: Optional[str] = typer.Option(None, "--owner", help="GitHub owner (for 'github' adapter)."),
    repo: Optional[str] = typer.Option(None, "--repo", help="GitHub repo name (for 'github' adapter)."),
    token_ref: Optional[str] = typer.Option(None, "--token-ref", help="Secret vault ref for GitHub token."),
) -> None:
    """Configure a new source adapter."""
    if adapter_type not in VALID_TYPES:
        console.print(f"[red]Invalid adapter type:[/red] {adapter_type}. Must be one of: {', '.join(VALID_TYPES)}")
        raise typer.Exit(code=1)

    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    adapter_config = _build_config(adapter_type, path=path, repo_url=repo_url,
                                    owner=owner, repo=repo, token_ref=token_ref)
    if isinstance(adapter_config, str):
        console.print(f"[red]error:[/red] {adapter_config}")
        raise typer.Exit(code=1)

    from llmwiki.core.adapters.source_repository import insert_source

    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            source_id = insert_source(conn, slug, adapter_type, name, adapter_config)
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    console.print(f"[green]Source added:[/green] {name} ({adapter_type}) -> {source_id}")


def source_list_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
) -> None:
    """List configured source adapters."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    from llmwiki.core.adapters.source_repository import list_sources

    with connect(db_path(home)) as conn:
        sources = list_sources(conn, slug)

    if not sources:
        console.print(f"[yellow]No sources configured for workspace {slug}.[/yellow]")
        return

    table = Table(title=f"Sources in {slug}")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Enabled")
    table.add_column("Created")

    for src in sources:
        table.add_row(
            src.source_id,
            src.name,
            src.adapter_type,
            "yes" if src.enabled else "no",
            src.created_at[:10],
        )

    console.print(table)


def source_remove_command(
    source_id: str = typer.Argument(..., help="Source ID to remove."),
) -> None:
    """Remove a configured source adapter."""
    home = resolve_home()
    from llmwiki.core.adapters.source_repository import remove_source

    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            removed = remove_source(conn, source_id)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    if removed:
        console.print(f"[green]Removed source:[/green] {source_id}")
    else:
        console.print(f"[yellow]Source not found:[/yellow] {source_id}")


def _build_config(
    adapter_type: str,
    path: str | None = None,
    repo_url: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    token_ref: str | None = None,
) -> dict | str:
    """Build adapter config dict or return error message."""
    if adapter_type == "local":
        if not path:
            return "'--path' is required for local adapter"
        return {"path": path}

    if adapter_type == "git-local":
        if not repo_url:
            return "'--repo-url' is required for git-local adapter"
        return {"repo_url": repo_url}

    if adapter_type == "github":
        if not owner or not repo:
            return "'--owner' and '--repo' are required for github adapter"
        cfg: dict = {"owner": owner, "repo": repo}
        if token_ref:
            cfg["token_ref"] = token_ref
        return cfg

    return f"unknown adapter type: {adapter_type}"
