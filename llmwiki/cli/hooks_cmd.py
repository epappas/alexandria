"""``llmwiki hooks`` — install/uninstall/verify agent hooks."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

console = Console()

SUPPORTED_CLIENTS = ("claude-code", "codex")


def hooks_install_command(
    client: str = typer.Argument(..., help="Client: claude-code | codex"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Install Stop + PreCompact hooks into a client."""
    if client not in SUPPORTED_CLIENTS:
        console.print(f"[red]Unknown client:[/red] {client}. Supported: {', '.join(SUPPORTED_CLIENTS)}")
        raise typer.Exit(code=1)

    if client == "claude-code":
        from llmwiki.hooks.installer.claude_code import install_claude_code_hooks
        result = install_claude_code_hooks(workspace)
    else:
        from llmwiki.hooks.installer.codex import install_codex_hooks
        result = install_codex_hooks(workspace)

    console.print(f"[green]Hooks installed for {client}:[/green]")
    for hook in result.get("hooks_installed", []):
        console.print(f"  {hook}")
    console.print(f"[dim]Settings: {result.get('settings_path')}[/dim]")
    console.print("[dim]Restart your client to activate.[/dim]")


def hooks_uninstall_command(
    client: str = typer.Argument(..., help="Client: claude-code | codex"),
) -> None:
    """Remove llmwiki-managed hooks from a client."""
    if client == "claude-code":
        from llmwiki.hooks.installer.claude_code import uninstall_claude_code_hooks
        removed = uninstall_claude_code_hooks()
    elif client == "codex":
        from llmwiki.hooks.installer.codex import uninstall_codex_hooks
        removed = uninstall_codex_hooks()
    else:
        console.print(f"[red]Unknown client:[/red] {client}")
        raise typer.Exit(code=1)

    if removed:
        console.print(f"[green]Hooks removed for {client}.[/green]")
    else:
        console.print(f"[yellow]No llmwiki hooks found for {client}.[/yellow]")


def hooks_verify_command(
    client: Optional[str] = typer.Argument(None, help="Client to verify (default: all)."),
) -> None:
    """Verify hook installation and protocol version."""
    clients = [client] if client else list(SUPPORTED_CLIENTS)
    all_ok = True

    for c in clients:
        if c == "claude-code":
            from llmwiki.hooks.installer.claude_code import verify_claude_code_hooks
            result = verify_claude_code_hooks()
        else:
            continue

        if result["installed"]:
            console.print(f"[green]{c}:[/green] hooks OK")
            for event, info in result.get("hooks", {}).items():
                console.print(f"  {event}: v{info['version']}")
        else:
            all_ok = False
            console.print(f"[red]{c}:[/red] issues found")
            for issue in result.get("issues", []):
                console.print(f"  [yellow]{issue}[/yellow]")

    if not all_ok:
        raise typer.Exit(code=1)
