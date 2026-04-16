"""``llmwiki reindex`` — Phase 0 ships ``--fts-verify`` (mlops F4)."""

from __future__ import annotations

import typer
from rich.console import Console

from llmwiki.config import resolve_home
from llmwiki.core.fts_integrity import check_fts_integrity, rebuild_fts
from llmwiki.db.connection import connect, db_path

console = Console()


def reindex_callback(
    ctx: typer.Context,
    fts_verify: bool = typer.Option(
        False,
        "--fts-verify",
        help="Run the FTS5 native integrity check + row-count compare.",
    ),
    fts_rebuild: bool = typer.Option(
        False,
        "--fts-rebuild",
        help="Force a full FTS5 rebuild (O(N), always correct).",
    ),
) -> None:
    """Reindex SQLite from the filesystem.

    Phase 0 ships only the FTS5 helpers. Full document reindex from the
    filesystem arrives in Phase 1 alongside the read-only MCP tools.
    """
    if ctx.invoked_subcommand is not None:
        return  # nothing — placeholder for future sub-commands
    if not fts_verify and not fts_rebuild:
        typer.echo(
            "Pass --fts-verify or --fts-rebuild. "
            "Full filesystem reindex arrives in Phase 1."
        )
        raise typer.Exit(code=1)

    home = resolve_home()
    if not db_path(home).exists():
        console.print("[yellow]No database. Run llmwiki init first.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        if fts_rebuild:
            console.print("[yellow]Rebuilding documents_fts...[/yellow]")
            rebuild_fts(conn)
            console.print("[green]Rebuild complete.[/green]")
        if fts_verify:
            report = check_fts_integrity(conn)
            console.print(f"[bold]FTS integrity:[/bold] {report.status}")
            console.print(f"  Content rows: {report.content_rows}")
            console.print(f"  FTS rows:     {report.fts_rows}")
            if report.error_message:
                console.print(f"  [yellow]Note:[/yellow] {report.error_message}")
            if report.status != "ok":
                raise typer.Exit(code=2)
