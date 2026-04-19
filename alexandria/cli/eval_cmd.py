"""``alexandria eval`` — evaluation metrics."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.db.connection import connect, db_path

console = Console()


def eval_run_command(
    metric: str = typer.Option("all", "--metric", "-m", help="Metric: M1|M2|M4|M5|all"),
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run evaluation metrics."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    from alexandria.eval.runner import run_all_metrics, run_metric

    with connect(db_path(home)) as conn:
        if metric == "all":
            results = run_all_metrics(conn, slug)
        else:
            results = [run_metric(conn, slug, metric)]

    if json_output:
        console.print_json(json.dumps(
            [{"metric": r.metric, "score": r.score, "passed": r.passed, "detail": r.detail} for r in results]
        ))
        return

    table = Table(title=f"Eval results for {slug}")
    table.add_column("Metric")
    table.add_column("Score")
    table.add_column("Status")
    table.add_column("Detail")

    for r in results:
        color = "green" if r.passed else "red"
        table.add_row(
            r.metric,
            f"{r.score:.2f}",
            f"[{color}]{'PASS' if r.passed else 'FAIL'}[/{color}]",
            json.dumps(r.detail, default=str)[:60],
        )

    console.print(table)


def eval_report_command(
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
    since: str = typer.Option("30d", "--since"),
) -> None:
    """Show evaluation history."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    with connect(db_path(home)) as conn:
        rows = conn.execute(
            """SELECT metric, score, passed, started_at FROM eval_runs
            WHERE workspace = ? ORDER BY started_at DESC LIMIT 20""",
            (slug,),
        ).fetchall()

    if not rows:
        console.print("[yellow]No eval runs found.[/yellow]")
        return

    table = Table(title=f"Eval history for {slug}")
    table.add_column("Metric")
    table.add_column("Score")
    table.add_column("Status")
    table.add_column("Date")

    for row in rows:
        color = "green" if row["passed"] else "red"
        table.add_row(
            row["metric"],
            f"{row['score']:.2f}" if row["score"] is not None else "-",
            f"[{color}]{'PASS' if row['passed'] else 'FAIL'}[/{color}]",
            row["started_at"][:16] if row["started_at"] else "",
        )
    console.print(table)
