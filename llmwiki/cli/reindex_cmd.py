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
    rebuild_beliefs: bool = typer.Option(
        False,
        "--rebuild-beliefs",
        help="Walk wiki pages and rebuild wiki_beliefs from content + sidecars.",
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w", help="Workspace to rebuild beliefs for.",
    ),
) -> None:
    """Reindex SQLite from the filesystem.

    --fts-verify: run the FTS5 native integrity check.
    --fts-rebuild: force a full FTS5 rebuild.
    --rebuild-beliefs: walk wiki pages and extract beliefs into wiki_beliefs.
    """
    if ctx.invoked_subcommand is not None:
        return
    if not fts_verify and not fts_rebuild and not rebuild_beliefs:
        typer.echo(
            "Pass --fts-verify, --fts-rebuild, or --rebuild-beliefs."
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

    if rebuild_beliefs:
        _rebuild_beliefs(home, workspace)


def _rebuild_beliefs(home: "Path", workspace_slug: str | None) -> None:
    """Walk wiki pages and rebuild wiki_beliefs from content + sidecars.

    This is the B6 backfill path: retroactively processes Phase 2 wiki pages
    that were written before the belief extractor existed. Also serves as the
    disaster-recovery path for wiki_beliefs table corruption.
    """
    from pathlib import Path
    from llmwiki.config import load_config, resolve_workspace
    from llmwiki.core.workspace import get_workspace, list_workspaces
    from llmwiki.core.beliefs.extractor import extract_beliefs_from_page
    from llmwiki.core.beliefs.sidecar import read_sidecar, write_sidecar
    from llmwiki.core.beliefs.repository import insert_belief

    config = load_config(home)
    if workspace_slug:
        workspaces_to_process = [get_workspace(home, workspace_slug)]
    else:
        workspaces_to_process = list_workspaces(home)

    total_beliefs = 0
    total_pages = 0

    with connect(db_path(home)) as conn:
        for ws in workspaces_to_process:
            wiki_dir = ws.path / "wiki"
            if not wiki_dir.exists():
                continue

            console.print(f"[dim]Processing workspace: {ws.slug}[/dim]")

            for md_file in sorted(wiki_dir.rglob("*.md")):
                if not md_file.is_file():
                    continue
                if md_file.name in ("index.md", "log.md"):
                    continue

                total_pages += 1
                rel_path = str(md_file.relative_to(ws.path))
                content = md_file.read_text(encoding="utf-8")

                # Infer topic from directory
                parts = md_file.relative_to(wiki_dir).parts
                topic = parts[0] if len(parts) > 1 else "general"

                # Try sidecar first; fall back to extraction
                sidecar_beliefs = read_sidecar(md_file, workspace=ws.slug)
                if sidecar_beliefs:
                    for belief in sidecar_beliefs:
                        belief.wiki_document_path = rel_path
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            insert_belief(conn, belief)
                            conn.execute("COMMIT")
                        except Exception:
                            conn.execute("ROLLBACK")
                            raise
                        total_beliefs += 1
                else:
                    # Extract from page content (the B6 backfill path)
                    beliefs = extract_beliefs_from_page(
                        content, rel_path, ws.slug, topic
                    )
                    for belief in beliefs:
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            insert_belief(conn, belief)
                            conn.execute("COMMIT")
                        except Exception:
                            conn.execute("ROLLBACK")
                            raise
                        total_beliefs += 1

                    # Write the sidecar so future rebuilds are faster
                    if beliefs:
                        write_sidecar(md_file, beliefs)

    console.print(
        f"[green]Rebuilt beliefs:[/green] {total_beliefs} beliefs "
        f"from {total_pages} pages across {len(workspaces_to_process)} workspace(s)"
    )
