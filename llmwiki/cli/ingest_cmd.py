"""``llmwiki ingest`` — compile a source into the wiki."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from llmwiki.config import load_config, resolve_home, resolve_workspace
from llmwiki.core.workspace import WorkspaceNotFoundError, get_workspace

console = Console()


def ingest_command(
    source: str = typer.Argument(..., help="Path to the source file to ingest."),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Override the current workspace."
    ),
    topic: Optional[str] = typer.Option(
        None, "--topic", help="Topic directory for the wiki page (default: inferred)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview the estimated cost without running."
    ),
) -> None:
    """Compile a raw source file into the wiki via staged writes + verification.

    The source is copied to ``raw/local/``, a wiki page is staged with
    citations, the deterministic verifier checks every footnote's verbatim
    quote against the live raw source, and on success the staged page is
    committed to ``wiki/``. A fabricated citation is always rejected.
    """
    home = resolve_home()
    config = load_config(home)
    target_slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, target_slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        console.print(f"[red]error:[/red] source file not found: {source}")
        raise typer.Exit(code=1)

    if dry_run:
        from llmwiki.llm.budget import BudgetConfig, BudgetEnforcer

        budget = BudgetEnforcer(BudgetConfig())
        est = budget.pre_flight_estimate(
            estimated_writer_calls=1,
            avg_input_per_call=4000,
            avg_output_per_call=2000,
        )
        console.print(f"[bold]Dry run preview:[/bold]")
        console.print(f"  Source:       {source_path}")
        console.print(f"  Workspace:    {target_slug}")
        console.print(f"  Topic:        {topic or '(inferred)'}")
        console.print(f"  Est. cost:    ${est:.4f}")
        console.print(f"[dim]Run without --dry-run to execute.[/dim]")
        return

    from llmwiki.core.ingest import IngestError, ingest_file

    try:
        result = ingest_file(
            home=home,
            workspace_slug=target_slug,
            workspace_path=ws.path,
            source_file=source_path,
            topic=topic,
        )
    except IngestError as exc:
        console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if result.committed:
        console.print(f"[green]Ingest committed[/green] (run {result.run_id})")
        for path in result.committed_paths:
            console.print(f"  [cyan]wiki/{path}[/cyan]")
        console.print(f"[dim]Verifier: {result.verdict_reasoning}[/dim]")
    else:
        console.print(f"[red]Ingest rejected[/red] (run {result.run_id})")
        console.print(f"[yellow]Reason:[/yellow] {result.verdict_reasoning}")
        console.print(f"[dim]Run `llmwiki runs show {result.run_id}` to inspect.[/dim]")
        raise typer.Exit(code=1)
