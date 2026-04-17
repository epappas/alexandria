"""``alexandria query`` — answer questions from the knowledge base."""

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
    """Answer a question by searching your knowledge base.

    Uses the LLM to understand your question, extract search terms,
    retrieve relevant content, and synthesize an answer with citations.
    Requires a configured LLM provider.
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

    with connect(db_path(home)) as conn:
        from alexandria.core.llm_query import llm_query
        result = llm_query(conn, slug, question, limit)

    if result is None:
        console.print("[red]No LLM provider configured.[/red]")
        console.print("Alexandria requires an LLM to understand and answer questions.\n")
        console.print("Configure one of:")
        console.print("  export ANTHROPIC_API_KEY=sk-ant-...")
        console.print("  export OPENAI_API_KEY=sk-...")
        console.print("  export OPENROUTER_API_KEY=sk-or-...")
        console.print("  export GOOGLE_API_KEY=AIza...")
        console.print("  pip install 'alexandria-wiki[claude]'  # uses Max/Pro subscription")
        console.print("\nOr set [llm] in ~/.alexandria/config.toml for local models (Ollama, vLLM).")
        raise typer.Exit(code=1)

    if json_output:
        import json
        console.print_json(json.dumps(result, default=str))
        return

    console.print(f"\n[bold]Answer:[/bold]\n")
    console.print(result["answer"])

    if result.get("sources"):
        console.print(f"\n[bold]Sources ({len(result['sources'])}):[/bold]")
        for s in result["sources"]:
            console.print(f"  [dim]{s['title']}[/dim] — {s['path']}")

    if result.get("beliefs"):
        console.print(f"\n[bold]Related beliefs ({len(result['beliefs'])}):[/bold]")
        for b in result["beliefs"]:
            console.print(f"  {b['statement']}")
            console.print(f"    [dim]topic: {b['topic']}[/dim]")

    if result.get("keywords"):
        console.print(f"\n[dim]Search terms: {', '.join(result['keywords'])}[/dim]")
