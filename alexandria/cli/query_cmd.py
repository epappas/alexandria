"""``alexandria query`` — answer questions from the wiki using FTS + beliefs."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.core.workspace import get_workspace, WorkspaceNotFoundError
from alexandria.db.connection import connect, db_path

console = Console()


def query_command(
    question: str = typer.Argument(..., help="The question to answer."),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results per source."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Answer a question by searching across wiki documents, beliefs, and events.

    Combines FTS5 search over documents, belief queries, and event search
    to produce a structured answer with citations. Read-only, no LLM calls.
    """
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not db_path(home).exists():
        console.print("[yellow]No database. Run alexandria init first.[/yellow]")
        raise typer.Exit(code=1)

    results = _search_all(home, slug, question, limit)

    if json_output:
        import json
        console.print_json(json.dumps(results, default=str))
        return

    if not any(results.values()):
        console.print(f"[yellow]No results for[/yellow] [bold]{question}[/bold] in {slug}")
        console.print("[dim]Try broader terms, or ingest more content first.[/dim]")
        return

    console.print(f"\n[bold]Results for[/bold] [cyan]{question}[/cyan] in {slug}:\n")

    docs = results.get("documents", [])
    if docs:
        console.print(f"[bold]Documents ({len(docs)}):[/bold]")
        for doc in docs:
            title = doc.get("title") or doc.get("path", "")
            console.print(f"  {title}")
            snippet = doc.get("snippet", "")
            if snippet:
                console.print(f"    [dim]{snippet[:120]}[/dim]")
        console.print()

    beliefs = results.get("beliefs", [])
    if beliefs:
        console.print(f"[bold]Beliefs ({len(beliefs)}):[/bold]")
        for b in beliefs:
            console.print(f"  {b['statement']}")
            console.print(f"    [dim]topic: {b['topic']} | page: {b['page']}[/dim]")
        console.print()

    events = results.get("events", [])
    if events:
        console.print(f"[bold]Events ({len(events)}):[/bold]")
        for ev in events:
            console.print(f"  [{ev.get('source_type', '')}] {ev.get('title', '')}")
            console.print(f"    [dim]{ev.get('occurred_at', '')[:10]}[/dim]")
        console.print()

    subs = results.get("subscriptions", [])
    if subs:
        console.print(f"[bold]Subscriptions ({len(subs)}):[/bold]")
        for s in subs:
            console.print(f"  {s.get('title', '')}")
            console.print(f"    [dim]{s.get('adapter_type', '')} | {s.get('published_at', '')[:10]}[/dim]")


def _search_all(home, slug: str, question: str, limit: int) -> dict:
    """Search across all knowledge sources."""
    results: dict = {"documents": [], "beliefs": [], "events": [], "subscriptions": []}

    with connect(db_path(home)) as conn:
        # FTS search on documents
        try:
            rows = conn.execute(
                """SELECT title, path, content FROM documents_fts
                JOIN documents ON documents.rowid = documents_fts.rowid
                WHERE documents_fts MATCH ? AND documents.workspace = ?
                ORDER BY rank LIMIT ?""",
                (question, slug, limit),
            ).fetchall()
            results["documents"] = [
                {"title": r["title"], "path": r["path"], "snippet": (r["content"] or "")[:150]}
                for r in rows
            ]
        except Exception:
            pass

        # Belief search
        try:
            rows = conn.execute(
                """SELECT statement, topic, wiki_document_path FROM wiki_beliefs_fts
                JOIN wiki_beliefs ON wiki_beliefs.rowid = wiki_beliefs_fts.rowid
                WHERE wiki_beliefs_fts MATCH ? AND wiki_beliefs.workspace = ?
                AND wiki_beliefs.superseded_at IS NULL
                ORDER BY rank LIMIT ?""",
                (question, slug, limit),
            ).fetchall()
            results["beliefs"] = [
                {"statement": r["statement"], "topic": r["topic"], "page": r["wiki_document_path"]}
                for r in rows
            ]
        except Exception:
            pass

        # Event search
        try:
            rows = conn.execute(
                """SELECT e.title, e.source_type, e.occurred_at FROM events_fts
                JOIN events e ON e.rowid = events_fts.rowid
                WHERE events_fts MATCH ? AND e.workspace = ?
                ORDER BY e.occurred_at DESC LIMIT ?""",
                (question, slug, limit),
            ).fetchall()
            results["events"] = [
                {"title": r["title"], "source_type": r["source_type"], "occurred_at": r["occurred_at"]}
                for r in rows
            ]
        except Exception:
            pass

        # Subscription search
        try:
            rows = conn.execute(
                """SELECT si.title, si.adapter_type, si.published_at
                FROM subscription_items_fts
                JOIN subscription_items si ON si.rowid = subscription_items_fts.rowid
                WHERE subscription_items_fts MATCH ? AND si.workspace = ?
                ORDER BY si.published_at DESC LIMIT ?""",
                (question, slug, limit),
            ).fetchall()
            results["subscriptions"] = [
                {"title": r["title"], "adapter_type": r["adapter_type"], "published_at": r["published_at"]}
                for r in rows
            ]
        except Exception:
            pass

    return results
