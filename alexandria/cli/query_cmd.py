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
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
    save: bool = typer.Option(False, "--save", help="Save the answer as a wiki page."),
) -> None:
    """Answer a question by navigating your knowledge base.

    Spawns an agent loop that uses Alexandria's navigation primitives
    (search, grep, read, beliefs) to find relevant content and
    synthesize an answer with citations.
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
        from alexandria.core.agent_loop import run_agent_query
        try:
            result = run_agent_query(conn, slug, ws.path, question)
        except RuntimeError as exc:
            console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if result is None:
        console.print("[red]No LLM provider configured.[/red]")
        console.print("Alexandria requires an LLM to answer questions.\n")
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
        console.print(f"\n[bold]Sources:[/bold]")
        for s in result["sources"]:
            console.print(f"  {s.get('title', '')} — {s.get('path', '')}")

    if result.get("tool_calls"):
        console.print(f"\n[dim]Agent used {len(result['tool_calls'])} tool call(s)[/dim]")

    if save and result:
        from alexandria.core.query_save import save_query_as_page
        with connect(db_path(home)) as conn:
            sr = save_query_as_page(home, slug, ws.path, question, result, conn)
        if sr.committed:
            console.print(f"\n[green]Saved to wiki[/green]")
            for p in sr.committed_paths:
                console.print(f"  [cyan]wiki/{p}[/cyan]")
