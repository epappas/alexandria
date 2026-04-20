"""``alexandria mcp`` group — serve / install / status."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from alexandria.config import resolve_home

console = Console()


def serve_command(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Pin the server to one workspace (pinned mode). Omit for open mode.",
    ),
) -> None:
    """Start the stdio MCP server.

    Open mode (no ``--workspace``): all workspaces accessible, every tool
    requires an explicit ``workspace`` argument.

    Pinned mode (``--workspace <slug>``): locked to one workspace.
    """
    from alexandria.mcp.server import run_stdio

    # Log to stderr (stdout is the MCP protocol channel)
    stderr_console = Console(stderr=True)
    stderr_console.print(
        f"[dim]alexandria MCP server starting on stdio"
        f"{' (pinned: ' + workspace + ')' if workspace else ' (open mode)'}[/dim]"
    )
    run_stdio(pinned_workspace=workspace)


def serve_http_command(
    workspace: str | None = typer.Option(None, "--workspace", "-w"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(7219, "--port"),
) -> None:
    """Start the MCP server over HTTP+SSE (Phase 6b transport)."""
    from alexandria.mcp.server import run_http

    stderr_console = Console(stderr=True)
    stderr_console.print(
        f"[dim]alexandria MCP HTTP server starting on {host}:{port}"
        f"{' (pinned: ' + workspace + ')' if workspace else ' (open mode)'}[/dim]"
    )
    run_http(pinned_workspace=workspace, host=host, port=port)


def install_command(
    client: str = typer.Argument(
        ...,
        help="Client to install into: claude-code | claude-desktop | cursor | codex | windsurf",
    ),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Pin the installed server to one workspace.",
    ),
) -> None:
    """Register alexandria as an MCP server in a client's config file.

    Writes a marker-tagged entry so ``alexandria mcp uninstall`` can remove it
    cleanly without touching user-authored entries.
    """
    installers = {
        "claude-code": _install_claude_code,
        "claude-desktop": _install_claude_desktop,
    }
    handler = installers.get(client)
    if not handler:
        supported = ", ".join(sorted(installers.keys()))
        console.print(f"[red]Unknown client:[/red] {client}")
        console.print(f"[dim]Supported: {supported}[/dim]")
        raise typer.Exit(code=1)
    handler(workspace)


def status_command() -> None:
    """Show MCP server registration status."""
    resolve_home()
    configs = _detect_registrations()
    if not configs:
        console.print("[yellow]No alexandria MCP registrations detected.[/yellow]")
        console.print("[dim]Run: alexandria mcp install claude-code[/dim]")
        return
    for client, path, config in configs:
        console.print(f"[green]{client}[/green] — {path}")
        if isinstance(config, dict):
            args = config.get("args", [])
            mode = "pinned" if "--workspace" in args else "open"
            console.print(f"  [dim]mode: {mode}[/dim]")


def _install_claude_code(workspace: str | None) -> None:
    """Write an MCP server entry to Claude Code's config."""
    alexandria_bin = _find_alexandria_bin()
    args = ["mcp", "serve"]

    # Auto-pin when only one workspace exists
    if not workspace:
        try:
            from alexandria.core.workspace import list_workspaces
            workspaces = list_workspaces(resolve_home())
            if len(workspaces) == 1:
                workspace = workspaces[0].slug
                console.print(f"[dim]Auto-pinning to workspace: {workspace}[/dim]")
        except Exception:
            pass  # no DB yet — proceed in open mode

    if workspace:
        args.extend(["--workspace", workspace])

    entry = {
        "command": alexandria_bin,
        "args": args,
        "_alexandria_managed": True,
    }

    # Write to project-scoped .mcp.json
    project_config = Path.cwd() / ".mcp.json"
    config = _read_json(project_config) or {}
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"]["alexandria"] = entry
    _write_json(project_config, config)

    mode = f"pinned: {workspace}" if workspace else "open mode"
    console.print(
        f"[green]Installed[/green] alexandria MCP server ({mode}) "
        f"in [bold]{project_config}[/bold]"
    )

    # Also update global registration via claude CLI
    try:
        subprocess.run(
            ["claude", "mcp", "remove", "alexandria"],
            capture_output=True, text=True, check=False,
        )
        subprocess.run(
            ["claude", "mcp", "add", "alexandria", "--", alexandria_bin, *args],
            capture_output=True, text=True, check=True,
        )
        console.print("[green]Global registration updated[/green]")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass  # claude CLI not available — project .mcp.json is enough

    # Re-write .mcp.json (claude mcp remove may have cleared it)
    config = _read_json(project_config) or {}
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"]["alexandria"] = entry
    _write_json(project_config, config)

    console.print("[dim]Restart your MCP client to pick up the change.[/dim]")


def _install_claude_desktop(workspace: str | None) -> None:
    """Write an MCP server entry to Claude Desktop's config."""
    import platform

    alexandria_bin = _find_alexandria_bin()
    args = ["mcp", "serve"]
    if workspace:
        args.extend(["--workspace", workspace])

    entry = {
        "command": alexandria_bin,
        "args": args,
        "_alexandria_managed": True,
    }

    system = platform.system()
    if system == "Darwin":
        config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming" / "Claude"
        config_path = appdata / "claude_desktop_config.json"
    else:
        config_path = Path.home() / ".config" / "claude" / "claude_desktop_config.json"

    config = _read_json(config_path) or {}
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    config["mcpServers"]["alexandria"] = entry
    _write_json(config_path, config)
    console.print(
        f"[green]Installed[/green] alexandria MCP server in "
        f"[bold]{config_path}[/bold]"
    )
    console.print("[dim]Restart Claude Desktop to pick up the change.[/dim]")


def _find_alexandria_bin() -> str:
    """Find the alexandria binary path."""
    import shutil

    found = shutil.which("alexandria")
    if found:
        return found
    return sys.executable + " -m alexandria"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _detect_registrations() -> list[tuple[str, str, dict]]:
    """Detect installed alexandria MCP registrations across known client configs."""
    results: list[tuple[str, str, dict]] = []

    # Check project-scoped .mcp.json
    mcp_json = Path.cwd() / ".mcp.json"
    _check_config(mcp_json, "project (.mcp.json)", results)

    # Check Claude Code user config
    claude_json = Path.home() / ".claude.json"
    _check_config(claude_json, "claude-code (~/.claude.json)", results)

    return results


def _check_config(
    path: Path, label: str, results: list[tuple[str, str, dict]]
) -> None:
    config = _read_json(path)
    if not config:
        return
    servers = config.get("mcpServers", {})
    if "alexandria" in servers:
        entry = servers["alexandria"]
        if isinstance(entry, dict) and entry.get("_alexandria_managed"):
            results.append((label, str(path), entry))
