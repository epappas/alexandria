"""``alexandria source`` — manage configured source adapters."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import get_workspace, WorkspaceNotFoundError
from alexandria.db.connection import connect, db_path

console = Console()

VALID_TYPES = ("local", "git-local", "github", "rss", "imap", "youtube", "notion", "huggingface", "folder", "archive")


def source_add_command(
    adapter_type: str = typer.Argument(..., help="Adapter type: local|git-local|github|rss|imap|youtube|notion|huggingface|folder|archive"),
    name: str = typer.Option(..., "--name", "-n", help="Human-readable name for this source."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    path: Optional[str] = typer.Option(None, "--path", help="Path (for local/folder/archive adapters)."),
    repo_url: Optional[str] = typer.Option(None, "--repo-url", help="Git repo URL."),
    owner: Optional[str] = typer.Option(None, "--owner", help="GitHub owner."),
    repo: Optional[str] = typer.Option(None, "--repo", help="GitHub repo name."),
    token_ref: Optional[str] = typer.Option(None, "--token-ref", help="Secret vault ref for token."),
    feed_url: Optional[str] = typer.Option(None, "--feed-url", help="RSS/Atom feed URL."),
    urls: Optional[str] = typer.Option(None, "--urls", help="Comma-separated URLs (youtube)."),
    repos: Optional[str] = typer.Option(None, "--repos", help="Comma-separated repo IDs (huggingface)."),
    page_ids: Optional[str] = typer.Option(None, "--page-ids", help="Comma-separated Notion page IDs."),
    database_ids: Optional[str] = typer.Option(None, "--database-ids", help="Comma-separated Notion DB IDs."),
    imap_host: Optional[str] = typer.Option(None, "--imap-host", help="IMAP server host."),
    imap_user: Optional[str] = typer.Option(None, "--imap-user", help="IMAP username."),
    imap_pass_ref: Optional[str] = typer.Option(None, "--imap-pass-ref", help="Vault ref for IMAP password."),
    imap_folder: Optional[str] = typer.Option("INBOX", "--imap-folder", help="IMAP folder."),
    from_allowlist: Optional[str] = typer.Option(None, "--from-allowlist", help="Comma-separated sender filter."),
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

    adapter_config = _build_config(
        adapter_type, path=path, repo_url=repo_url, owner=owner, repo=repo,
        token_ref=token_ref, feed_url=feed_url, urls=urls, repos=repos,
        page_ids=page_ids, database_ids=database_ids,
        imap_host=imap_host, imap_user=imap_user, imap_pass_ref=imap_pass_ref,
        imap_folder=imap_folder, from_allowlist=from_allowlist,
    )
    if isinstance(adapter_config, str):
        console.print(f"[red]error:[/red] {adapter_config}")
        raise typer.Exit(code=1)

    from alexandria.core.adapters.source_repository import insert_source

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

    from alexandria.core.adapters.source_repository import list_sources

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
    from alexandria.core.adapters.source_repository import remove_source

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
    feed_url: str | None = None,
    urls: str | None = None,
    repos: str | None = None,
    page_ids: str | None = None,
    database_ids: str | None = None,
    imap_host: str | None = None,
    imap_user: str | None = None,
    imap_pass_ref: str | None = None,
    imap_folder: str | None = None,
    from_allowlist: str | None = None,
) -> dict | str:
    """Build adapter config dict or return error message."""
    if adapter_type == "local":
        if not path:
            return "'--path' is required for local adapter"
        return {"path": path}

    if adapter_type == "folder":
        if not path:
            return "'--path' is required for folder adapter"
        return {"path": path}

    if adapter_type == "archive":
        if not path:
            return "'--path' is required for archive adapter"
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

    if adapter_type == "rss":
        if not feed_url:
            return "'--feed-url' is required for rss adapter"
        return {"feed_url": feed_url}

    if adapter_type == "youtube":
        if not urls:
            return "'--urls' required (comma-separated YouTube URLs)"
        return {"urls": [u.strip() for u in urls.split(",")]}

    if adapter_type == "notion":
        cfg = {}
        if token_ref:
            cfg["token_ref"] = token_ref
        if page_ids:
            cfg["page_ids"] = [p.strip() for p in page_ids.split(",")]
        if database_ids:
            cfg["database_ids"] = [d.strip() for d in database_ids.split(",")]
        if not cfg.get("page_ids") and not cfg.get("database_ids"):
            return "'--page-ids' or '--database-ids' required for notion adapter"
        return cfg

    if adapter_type == "huggingface":
        if not repos:
            return "'--repos' required (comma-separated repo IDs like 'meta-llama/Llama-3-8b')"
        return {"repos": [r.strip() for r in repos.split(",")]}

    if adapter_type == "imap":
        if not imap_host or not imap_user:
            return "'--imap-host' and '--imap-user' are required for imap adapter"
        cfg = {"host": imap_host, "username": imap_user, "folder": imap_folder or "INBOX"}
        if imap_pass_ref:
            cfg["password_ref"] = imap_pass_ref
        if from_allowlist:
            cfg["from_allowlist"] = [a.strip() for a in from_allowlist.split(",")]
        return cfg

    return f"unknown adapter type: {adapter_type}"
