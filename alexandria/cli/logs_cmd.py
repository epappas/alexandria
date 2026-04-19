"""``alexandria logs`` — view structured daemon logs."""

from __future__ import annotations

import json

import typer
from rich.console import Console

from alexandria.config import resolve_home

console = Console()


def logs_show_command(
    run_id: str | None = typer.Argument(None, help="Filter by run_id."),
    family: str | None = typer.Option(None, "--family", "-f", help="Filter by log family."),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of recent lines to show."),
    json_output: bool = typer.Option(False, "--json", help="Raw JSON output."),
) -> None:
    """Show structured logs, optionally filtered by run_id or family."""
    home = resolve_home()
    log_dir = home / "logs"

    if not log_dir.exists():
        console.print("[yellow]No logs directory found.[/yellow]")
        raise typer.Exit(code=1)

    # Collect log files
    patterns = [f"{family}-*.jsonl"] if family else ["*.jsonl"]
    log_files = []
    for pattern in patterns:
        log_files.extend(sorted(log_dir.glob(pattern)))

    if not log_files:
        console.print("[yellow]No log files found.[/yellow]")
        return

    # Read and filter entries
    entries: list[dict] = []
    for path in log_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id and entry.get("run_id") != run_id:
                continue
            entries.append(entry)

    # Sort by timestamp and take tail
    entries.sort(key=lambda e: e.get("ts", ""))
    entries = entries[-tail:]

    if json_output:
        for e in entries:
            console.print_json(json.dumps(e, default=str))
        return

    for e in entries:
        ts = e.get("ts", "")[:19]
        level = e.get("level", "info")
        event = e.get("event", "")
        fam = e.get("family", "")

        level_color = {"info": "blue", "warn": "yellow", "error": "red"}.get(level, "dim")
        line = f"[dim]{ts}[/dim] [{level_color}]{level:5s}[/{level_color}] [{fam}] {event}"

        data = e.get("data")
        if data:
            line += f" [dim]{json.dumps(data, default=str)}[/dim]"

        console.print(line)
