"""``alexandria ingest-repo`` — ingest an entire repository."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace

console = Console()


def ingest_repo_command(
    source: str = typer.Argument(
        ..., help="Local directory path or git URL (GitHub, GitLab, etc.).",
    ),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Override the current workspace.",
    ),
    topic: Optional[str] = typer.Option(
        None, "--topic", help="Override topic for all files (default: inferred from path).",
    ),
) -> None:
    """Ingest all supported files from a local directory or git repo.

    Accepts a local path or a git URL. Git URLs are shallow-cloned to
    raw/git/ automatically. Walks the tree and ingests .py, .ts, .rs,
    .go, .tf, .yml, .md, and other supported files.
    """
    home = resolve_home()
    config = load_config(home)
    target_slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, target_slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    # Expand GitHub shorthand: owner/repo -> https://github.com/owner/repo.git
    if "/" in source and source.count("/") == 1 and not Path(source).exists():
        source = f"https://github.com/{source}.git"

    # Determine if source is a URL or local path
    if _is_git_url(source):
        console.print(f"[dim]Cloning {source}...[/dim]")
        from alexandria.core.repo_ingest import clone_repo, IngestError
        git_dir = ws.path / "raw" / "git"
        try:
            repo_path = clone_repo(source, git_dir)
        except IngestError as exc:
            console.print(f"[red]Clone failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        console.print(f"[dim]Repo at {repo_path.relative_to(ws.path)}[/dim]")
    else:
        repo_path = Path(source).expanduser().resolve()
        if not repo_path.is_dir():
            console.print(f"[red]error:[/red] not a directory: {source}")
            raise typer.Exit(code=1)

    # Count files first
    from alexandria.core.repo_ingest import _collect_files, ALL_INGEST_EXTS
    files = _collect_files(repo_path, ALL_INGEST_EXTS)
    console.print(f"Found [bold]{len(files)}[/bold] files to ingest")

    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return

    # Ingest with progress
    from alexandria.core.repo_ingest import ingest_repo

    def on_progress(rel: str, status: str) -> None:
        if status == "committed":
            console.print(f"  [green]+[/green] {rel}")
        elif status == "rejected":
            console.print(f"  [yellow]-[/yellow] {rel}")
        else:
            console.print(f"  [red]![/red] {rel}")

    result = ingest_repo(
        home=home,
        workspace_slug=target_slug,
        workspace_path=ws.path,
        repo_path=repo_path,
        topic=topic,
        on_progress=on_progress,
    )

    # Summary
    console.print()
    console.print(f"[bold]Results:[/bold]")
    console.print(f"  Committed: [green]{len(result.committed)}[/green]")
    if result.rejected:
        console.print(f"  Rejected:  [yellow]{len(result.rejected)}[/yellow]")
    if result.errors:
        console.print(f"  Errors:    [red]{len(result.errors)}[/red]")
        for err in result.errors[:5]:
            console.print(f"    {err}")


def _is_git_url(source: str) -> bool:
    """Detect if source is a git-cloneable URL."""
    if source.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    if source.endswith(".git"):
        return True
    # GitHub/GitLab shorthand: owner/repo
    if "/" in source and not Path(source).exists() and source.count("/") == 1:
        return True
    return False
