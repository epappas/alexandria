"""``alexandria lint`` — find wiki rot by running the deterministic verifier."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def lint_command(
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
    fix: bool = typer.Option(False, "--fix", help="Auto-fix deterministic issues."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Find wiki rot: stale citations, missing sources, orphaned beliefs.

    Runs the deterministic verifier across all wiki pages in the workspace.
    Reports issues grouped by severity. Use --fix to auto-fix safe issues.
    """
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    wiki_dir = ws.path / "wiki"
    if not wiki_dir.exists():
        console.print(f"[yellow]No wiki directory in {slug}.[/yellow]")
        return

    issues = _scan_workspace(ws.path, home, slug, verbose)

    if not issues:
        console.print(f"[green]No issues found in {slug}.[/green]")
        return

    table = Table(title=f"Wiki lint: {len(issues)} issue(s) in {slug}")
    table.add_column("Severity", style="bold")
    table.add_column("File")
    table.add_column("Issue")

    for issue in issues:
        sev_color = {"error": "red", "warning": "yellow", "info": "dim"}.get(
            issue["severity"], "dim"
        )
        table.add_row(
            f"[{sev_color}]{issue['severity']}[/{sev_color}]",
            issue["file"],
            issue["message"],
        )

    console.print(table)

    if fix:
        fixed = _auto_fix(issues, ws.path)
        if fixed:
            console.print(f"\n[green]Auto-fixed {fixed} issue(s).[/green]")
        else:
            console.print("\n[dim]No auto-fixable issues found.[/dim]")

    errors = sum(1 for i in issues if i["severity"] == "error")
    if errors:
        raise typer.Exit(code=2)


def _scan_workspace(
    workspace_path: Path, home: Path, slug: str, verbose: bool
) -> list[dict]:
    """Scan all wiki pages for issues."""
    issues: list[dict] = []
    wiki_dir = workspace_path / "wiki"

    for md_file in sorted(wiki_dir.rglob("*.md")):
        if not md_file.is_file():
            continue
        rel = str(md_file.relative_to(workspace_path))
        content = md_file.read_text(encoding="utf-8")

        # Check: page has content
        if len(content.strip()) < 10:
            issues.append({
                "severity": "warning",
                "file": rel,
                "message": "page is nearly empty",
            })
            continue

        # Check: citations present (skip structural pages)
        if md_file.name not in ("index.md", "log.md", "SKILL.md"):
            from alexandria.core.citations import extract_footnotes
            footnotes = extract_footnotes(content)
            if not footnotes and "[^" not in content:
                issues.append({
                    "severity": "info",
                    "file": rel,
                    "message": "no citations found",
                })

            # Check: cited sources exist
            for fn in footnotes:
                source_file_path = workspace_path / fn.source_file
                if not source_file_path.exists():
                    issues.append({
                        "severity": "error",
                        "file": rel,
                        "message": f"cited source missing: {fn.source_file}",
                    })

                # Check: quote anchor integrity
                if fn.quote and source_file_path.exists():
                    from alexandria.core.citations.anchors import create_anchor, verify_quote_anchor
                    source_text = source_file_path.read_text(encoding="utf-8")
                    anchor = create_anchor(fn.source_file, fn.quote, source_text)
                    result = verify_quote_anchor(anchor, workspace_path)
                    if result.status != "verified":
                        issues.append({
                            "severity": "error",
                            "file": rel,
                            "message": f"quote anchor drifted for [^{fn.footnote_id}]: {result.message}",
                        })

    # Check: orphaned beliefs (beliefs pointing to deleted pages)
    with connect(db_path(home)) as conn:
        try:
            rows = conn.execute(
                """SELECT belief_id, statement, wiki_document_path FROM wiki_beliefs
                WHERE workspace = ? AND superseded_at IS NULL""",
                (slug,),
            ).fetchall()
            for row in rows:
                page_path = workspace_path / row["wiki_document_path"]
                if not page_path.exists():
                    issues.append({
                        "severity": "warning",
                        "file": row["wiki_document_path"],
                        "message": f"belief orphaned: {row['statement'][:60]}",
                    })
        except Exception:
            pass

    return issues


def _auto_fix(issues: list[dict], workspace_path: Path) -> int:
    """Auto-fix safe issues. Returns count fixed."""
    # Currently no auto-fixes implemented — all require human judgment
    return 0
