"""``alexandria why`` — belief explainability with provenance + history."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.beliefs.repository import BeliefQuery, query_beliefs
from alexandria.core.workspace import WorkspaceNotFoundError, get_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def why_command(
    query: str = typer.Argument(..., help="Topic, subject, or belief id to look up."),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Override the current workspace."
    ),
    since: Optional[str] = typer.Option(
        None, "--since", help="Only beliefs current at or after this date."
    ),
    include_history: bool = typer.Option(
        True, "--history/--no-history", help="Include superseded beliefs."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Return beliefs matching the query with provenance + history.

    Read-only. No LLM calls. Pure SQL lookup over ``wiki_beliefs`` + FTS5.
    """
    home = resolve_home()
    config = load_config(home)
    target_slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, target_slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        # Try direct belief_id lookup first
        from alexandria.core.beliefs.repository import get_belief

        direct = get_belief(conn, query)
        if direct:
            beliefs = [direct]
        else:
            bq = BeliefQuery(
                workspace=target_slug,
                query=query,
                since=since,
                current_only=not include_history,
            )
            beliefs = query_beliefs(conn, bq)

        # Also fetch superseded beliefs for history
        history: list = []
        if include_history and beliefs:
            for b in beliefs:
                if b.superseded_by_belief_id:
                    successor = get_belief(conn, b.superseded_by_belief_id)
                    if successor:
                        history.append(successor)
            # Also find beliefs that were superseded by our results
            for b in list(beliefs):
                cur = conn.execute(
                    "SELECT * FROM wiki_beliefs WHERE superseded_by_belief_id = ?",
                    (b.belief_id,),
                )
                for row in cur.fetchall():
                    from alexandria.core.beliefs.repository import _row_to_belief
                    history.append(_row_to_belief(row))

    if json_output:
        payload = {
            "query": query,
            "workspace": target_slug,
            "current_beliefs": [b.to_dict() for b in beliefs if b.is_current],
            "history": [b.to_dict() for b in beliefs if not b.is_current] + [b.to_dict() for b in history],
        }
        console.print_json(json.dumps(payload))
        return

    if not beliefs and not history:
        console.print(f"[yellow]No beliefs found for[/yellow] [bold]{query}[/bold] in {target_slug}")
        console.print("[dim]Beliefs are created when content is ingested (alexandria ingest).[/dim]")
        return

    current = [b for b in beliefs if b.is_current]
    superseded = [b for b in beliefs if not b.is_current] + history

    if current:
        console.print(f"\n[bold]Current beliefs matching[/bold] [cyan]{query}[/cyan]:\n")
        for b in current:
            _print_belief(b)

    if superseded:
        console.print(f"\n[bold]Superseded beliefs (history):[/bold]\n")
        for b in superseded:
            _print_belief(b, superseded=True)


def _print_belief(b: object, superseded: bool = False) -> None:
    """Pretty-print a single belief."""
    from alexandria.core.beliefs.model import Belief
    assert isinstance(b, Belief)

    marker = "[dim][superseded][/dim] " if superseded else ""
    console.print(f"  {marker}[bold]{b.statement}[/bold]")
    console.print(f"    [dim]topic: {b.topic} | page: {b.wiki_document_path}[/dim]")
    if b.footnote_ids:
        console.print(f"    [dim]citations: {', '.join(f'[^{f}]' for f in b.footnote_ids)}[/dim]")
    console.print(f"    [dim]asserted: {b.asserted_at[:10]}[/dim]")
    if b.superseded_at:
        console.print(f"    [dim]superseded: {b.superseded_at[:10]} — {b.supersession_reason}[/dim]")
    if b.subject:
        console.print(f"    [dim]structured: {b.subject} {b.predicate} {b.object}[/dim]")
    console.print()
