"""``alexandria watch`` — auto-ingest on file changes."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace

console = Console()


def watch_command(
    path: str = typer.Argument(".", help="Directory to watch."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    debounce: int = typer.Option(500, "--debounce", help="Debounce interval in ms."),
) -> None:
    """Watch a directory and auto-ingest files on change.

    Monitors for new/modified files and ingests them through the
    full pipeline. Uses watchdog for cross-platform file events.
    """
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    watch_path = Path(path).expanduser().resolve()
    if not watch_path.is_dir():
        console.print(f"[red]error:[/red] not a directory: {path}")
        raise typer.Exit(code=1)

    def on_progress(rel: str, status: str) -> None:
        sym = {"committed": "[green]+[/green]", "skipped": "[dim]=[/dim]"}.get(status, "[red]![/red]")
        console.print(f"  {sym} {rel}")

    console.print(f"[dim]Watching {watch_path} (workspace: {slug}, debounce: {debounce}ms)[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        from alexandria.core.watcher import start_watcher
        start_watcher(
            home, slug, ws.path, watch_path,
            debounce_ms=debounce, on_progress=on_progress,
        )
    except RuntimeError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
