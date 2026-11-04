"""``alexandria reindex`` — Phase 0 ships ``--fts-verify`` (mlops F4)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape

from alexandria.config import resolve_home
from alexandria.core.fts_integrity import check_fts_integrity, rebuild_fts
from alexandria.db.connection import connect, db_path

if TYPE_CHECKING:
    from alexandria.core.beliefs.model import Belief

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
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
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


def _rebuild_beliefs(home: Path, workspace_slug: str | None) -> None:
    """Walk wiki pages and rebuild wiki_beliefs from content + sidecars.

    This is the B6 backfill path: retroactively processes Phase 2 wiki pages
    that were written before the belief extractor existed. Also serves as the
    disaster-recovery path for wiki_beliefs table corruption.
    """
    from alexandria.config import load_config
    from alexandria.core.beliefs.extractor import extract_beliefs_from_page
    from alexandria.core.beliefs.repository import insert_belief
    from alexandria.core.beliefs.sidecar import read_sidecar, write_sidecar
    from alexandria.core.workspace import get_workspace, list_workspaces

    load_config(home)
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

                # Try sidecar first; fall back to extraction (the B6 backfill path)
                sidecar_beliefs = read_sidecar(md_file, workspace=ws.slug)
                for belief in sidecar_beliefs:
                    belief.wiki_document_path = rel_path
                beliefs = sidecar_beliefs or extract_beliefs_from_page(
                    content, rel_path, ws.slug, topic
                )
                under_sj = _publish_page_beliefs(
                    home, ws.slug, ws.path, rel_path, content, beliefs,
                    stored_ids=bool(sidecar_beliefs),
                )
                for belief in beliefs:
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        # Under SJ an existing row is never rewritten from the sidecar, so a
                        # belief superseded since stays superseded.
                        insert_belief(conn, belief, replace=not under_sj)
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
                    total_beliefs += 1

                # Write the sidecar so future rebuilds are faster
                if beliefs and not sidecar_beliefs:
                    write_sidecar(md_file, beliefs)

    console.print(
        f"[green]Rebuilt beliefs:[/green] {total_beliefs} beliefs "
        f"from {total_pages} pages across {len(workspaces_to_process)} workspace(s)"
    )


def _publish_page_beliefs(
    home: Path, slug: str, ws_path: Path, rel_path: str, content: str, beliefs: list[Belief],
    *, stored_ids: bool,
) -> bool:
    """Publishes the page's cited beliefs into SJ when configured, and returns whether SJ is
    configured; a failure exits 2 before anything of this page is indexed locally. The
    operation is the page at its content hash; claims SJ already holds are not written again.
    Sidecar beliefs (`stored_ids`) keep their ids, so editing a page never re-asserts them
    under new ids."""
    from alexandria.core.sj_store import SjWriteError, publish_beliefs

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    try:
        publication = publish_beliefs(
            home, slug, ws_path, ("reindex", rel_path, digest), rel_path, beliefs,
            derive_ids=not stored_ids,
        )
    except SjWriteError as exc:
        console.print(f"[red]SJ write failed for {rel_path}:[/red] {escape(str(exc))}")
        raise typer.Exit(code=2) from exc
    for line in publication.lines() if publication else []:
        console.print(f"[dim]{rel_path}:[/dim] {escape(line)}")
    return publication is not None
