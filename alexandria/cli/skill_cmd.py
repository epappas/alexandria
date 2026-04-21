"""``alexandria skill`` group — install the alexandria skill into agents."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

import typer
from rich.console import Console

console = Console()


def install_command(
    client: str = typer.Argument(
        ...,
        help="Client to install into: claude-code | cursor | codex",
    ),
) -> None:
    """Install the alexandria skill into an AI coding agent.

    Writes ``SKILL.md`` (plus a client-specific always-on hook where the
    platform supports it) so the agent invokes alexandria tools before
    searching the filesystem or answering from training data.
    """
    installers = {
        "claude-code": _install_claude_code,
        "cursor": _install_cursor,
        "codex": _install_codex,
    }
    handler = installers.get(client)
    if not handler:
        supported = ", ".join(sorted(installers.keys()))
        console.print(f"[red]Unknown client:[/red] {client}")
        console.print(f"[dim]Supported: {supported}[/dim]")
        raise typer.Exit(code=1)
    handler()


def _skill_source() -> str:
    """Load the bundled SKILL.md text."""
    return (files("alexandria.skill") / "SKILL.md").read_text(encoding="utf-8")


def _install_claude_code() -> None:
    """Copy SKILL.md to ~/.claude/skills/alexandria/."""
    target_dir = Path.home() / ".claude" / "skills" / "alexandria"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    target.write_text(_skill_source(), encoding="utf-8")
    console.print(f"[green]Installed[/green] alexandria skill at [bold]{target}[/bold]")

    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    marker = "- **alexandria**"
    line = (
        "- **alexandria** (`~/.claude/skills/alexandria/SKILL.md`) — "
        "persistent knowledge base. Trigger: `/alexandria`\n"
    )
    if not claude_md.exists():
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text(line, encoding="utf-8")
    else:
        existing = claude_md.read_text(encoding="utf-8")
        if marker not in existing:
            claude_md.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    console.print(f"[dim]Registered in {claude_md}[/dim]")
    console.print("[dim]Restart Claude Code to pick up the skill.[/dim]")


def _install_cursor() -> None:
    """Write .cursor/rules/alexandria.mdc with alwaysApply: true."""
    rules_dir = Path.cwd() / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    target = rules_dir / "alexandria.mdc"
    header = (
        "---\n"
        "description: alexandria persistent knowledge base\n"
        "alwaysApply: true\n"
        "---\n\n"
    )
    target.write_text(header + _skill_source(), encoding="utf-8")
    console.print(f"[green]Installed[/green] alexandria rule at [bold]{target}[/bold]")
    console.print(
        "[dim]Cursor will include this in every conversation automatically.[/dim]"
    )


def _install_codex() -> None:
    """Append AGENTS.md entry and install a pre-bash hook in .codex/hooks.json."""
    import json

    agents_md = Path.cwd() / "AGENTS.md"
    marker = "## alexandria"
    body = "\n\n" + marker + "\n\n" + _skill_source()
    if not agents_md.exists():
        agents_md.write_text(body.lstrip(), encoding="utf-8")
    else:
        existing = agents_md.read_text(encoding="utf-8")
        if marker not in existing:
            agents_md.write_text(existing.rstrip() + body, encoding="utf-8")
    console.print(f"[green]Updated[/green] [bold]{agents_md}[/bold]")

    hooks_path = Path.cwd() / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    existing_hooks: dict = {}
    if hooks_path.exists():
        try:
            existing_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_hooks = {}
    pre_tool = existing_hooks.setdefault("PreToolUse", [])
    reminder = {
        "matcher": "Bash",
        "_alexandria_managed": True,
        "message": (
            "alexandria knowledge base is available via mcp__alexandria__* "
            "tools. Prefer search/grep over raw filesystem traversal for "
            "questions about previously ingested material."
        ),
    }
    pre_tool[:] = [h for h in pre_tool if not h.get("_alexandria_managed")]
    pre_tool.append(reminder)
    hooks_path.write_text(
        json.dumps(existing_hooks, indent=2) + "\n", encoding="utf-8",
    )
    console.print(f"[green]Installed[/green] pre-bash hook at [bold]{hooks_path}[/bold]")
