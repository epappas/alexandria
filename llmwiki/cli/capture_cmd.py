"""``llmwiki capture`` — conversation capture commands."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from llmwiki.config import load_config, resolve_home, resolve_workspace
from llmwiki.db.connection import connect, db_path

console = Console()


def capture_conversation_command(
    transcript: Optional[str] = typer.Argument(None, help="Path to transcript file."),
    client: str = typer.Option("claude-code", "--client", "-c"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    detach: bool = typer.Option(False, "--detach", help="Return immediately, capture in background."),
    reason: Optional[str] = typer.Option(None, "--reason", help="Capture reason (e.g., pre-compact)."),
) -> None:
    """Capture a conversation transcript into the knowledge engine."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    if detach:
        # Fork to background and return immediately
        cmd = [sys.executable, "-m", "llmwiki", "capture", "conversation"]
        if transcript:
            cmd.append(transcript)
        cmd.extend(["--client", client, "--workspace", slug])
        if reason:
            cmd.extend(["--reason", reason])
        subprocess.Popen(cmd, start_new_session=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    from llmwiki.core.workspace import get_workspace, WorkspaceNotFoundError

    try:
        ws = get_workspace(home, slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    # Auto-detect transcript if not provided
    if not transcript:
        transcript = _find_latest_transcript(client)
        if not transcript:
            console.print("[yellow]No transcript found to capture.[/yellow]")
            raise typer.Exit(code=1)

    from pathlib import Path
    from llmwiki.core.capture.conversation import capture_conversation, CaptureError

    try:
        result = capture_conversation(
            Path(transcript), ws.path, client,
        )
    except CaptureError as exc:
        console.print(f"[red]Capture failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]Captured:[/green] {result['message_count']} messages "
        f"-> {result['output_path']}"
    )


def captures_list_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
    status: Optional[str] = typer.Option(None, "--status"),
) -> None:
    """List captured conversations."""
    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    with connect(db_path(home)) as conn:
        sql = "SELECT * FROM capture_queue WHERE workspace = ?"
        params: list = [slug]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY enqueued_at DESC LIMIT 50"
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        console.print("[yellow]No captures found.[/yellow]")
        return

    table = Table(title=f"Captures in {slug}")
    table.add_column("Session", max_width=16)
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Enqueued")

    for row in rows:
        table.add_row(
            row["session_id"][:16],
            row["client"],
            row["status"],
            row["enqueued_at"][:16] if row["enqueued_at"] else "",
        )
    console.print(table)


def _find_latest_transcript(client: str) -> str | None:
    """Auto-detect the latest transcript file for the given client."""
    from pathlib import Path

    if client == "claude-code":
        # Claude Code stores conversations in ~/.claude/projects/
        claude_dir = Path.home() / ".claude" / "projects"
        if claude_dir.exists():
            jsonl_files = sorted(claude_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if jsonl_files:
                return str(jsonl_files[0])
    return None
