"""Helper for unimplemented CLI commands.

Per ``docs/architecture/20_cli_surface.md`` and ``docs/IMPLEMENTATION_PLAN.md``,
unimplemented CLI sub-commands are the **only** allowed exception to the
no-fakes rule, because the user must still be able to discover the surface
via ``llmwiki -h``. They print a clear "not yet shipped — planned for phase N"
message and exit with code 2.
"""

from __future__ import annotations

import sys

import typer
from rich.console import Console

_console = Console(stderr=True)


def phase_stub(phase: int, command: str, what: str) -> None:
    """Print a structured stub message and exit with code 2 (not-yet-shipped).

    Args:
        phase: the implementation-plan phase that will ship this command.
        command: the canonical command name (e.g. ``llmwiki query``).
        what: a one-line description of what the command will do when shipped.
    """
    _console.print(
        f"[yellow]llmwiki:[/yellow] [bold]{command}[/bold] is not yet shipped"
    )
    _console.print(f"[dim]Planned for Phase {phase}.[/dim]")
    _console.print(f"[dim]Will: {what}[/dim]")
    _console.print(
        f"[dim]See docs/IMPLEMENTATION_PLAN.md and docs/architecture/20_cli_surface.md.[/dim]"
    )
    raise typer.Exit(code=2)


def stub_command(phase: int, command: str, what: str) -> None:
    """Convenience for use as a Typer command body."""
    phase_stub(phase, command, what)


def _writeln(line: str) -> None:
    """Print to stderr without coloring (used in non-typer contexts)."""
    print(line, file=sys.stderr)
