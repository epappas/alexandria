"""``alexandria daemon`` — manage the supervised-subprocess daemon."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from alexandria.config import resolve_home

console = Console()


def daemon_start_command(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground (no daemonize)."),
) -> None:
    """Start the supervised-subprocess daemon."""
    home = resolve_home()
    from alexandria.daemon.parent import DaemonParent

    parent = DaemonParent(home)

    if parent.is_running():
        console.print("[yellow]Daemon is already running.[/yellow]")
        raise typer.Exit(code=1)

    if foreground:
        console.print("[dim]Starting daemon in foreground (Ctrl+C to stop)...[/dim]")
        parent.start()
    else:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            console.print(f"[green]Daemon started[/green] (pid {pid})")
            return
        # Child: detach
        os.setsid()
        parent.start()


def daemon_stop_command() -> None:
    """Stop the running daemon."""
    home = resolve_home()
    from alexandria.daemon.parent import DaemonParent

    parent = DaemonParent(home)
    if not parent.is_running():
        console.print("[yellow]Daemon is not running.[/yellow]")
        raise typer.Exit(code=1)

    pid = int(parent.pid_path.read_text().strip())

    # Verify the PID belongs to an alexandria process before sending signal
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            cmdline = cmdline_path.read_bytes().decode("utf-8", errors="replace")
            if "alexandria" not in cmdline:
                console.print(f"[red]PID {pid} is not an alexandria process. Stale PID file?[/red]")
                parent.pid_path.unlink(missing_ok=True)
                raise typer.Exit(code=1)
    except (OSError, PermissionError):
        pass  # non-Linux or no /proc access — proceed with caution

    os.kill(pid, signal.SIGTERM)
    console.print(f"[green]Sent SIGTERM to daemon[/green] (pid {pid})")


def daemon_status_command(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show daemon process state."""
    home = resolve_home()
    from alexandria.daemon.parent import DaemonParent

    parent = DaemonParent(home)
    status = parent.get_status()

    if json_output:
        console.print_json(json.dumps(status, default=str))
        return

    if not status["running"]:
        console.print("[yellow]Daemon is not running.[/yellow]")
        return

    console.print(f"[green]Daemon running[/green] (pid {status['pid']})")

    if status["children"]:
        table = Table(title="Children")
        table.add_column("Name")
        table.add_column("PID")
        table.add_column("State")
        table.add_column("Last Beat")

        for child in status["children"]:
            state_color = {
                "running": "green",
                "starting": "yellow",
                "draining": "yellow",
                "failed": "red",
            }.get(child["state"], "dim")
            table.add_row(
                child["child_name"],
                str(child["pid"]),
                f"[{state_color}]{child['state']}[/{state_color}]",
                child["last_beat"][:19] if child["last_beat"] else "",
            )
        console.print(table)
    else:
        console.print("[dim]No child processes.[/dim]")
