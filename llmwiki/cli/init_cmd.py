"""``llmwiki init`` — set up ~/.llmwiki/ and the global workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from llmwiki.config import (
    DEFAULT_WORKSPACE_SLUG,
    Config,
    GeneralConfig,
    StateConfig,
    config_path,
    resolve_home,
    save_config,
)
from llmwiki.core.workspace import (
    GLOBAL_SLUG,
    WorkspaceExistsError,
    init_workspace,
)
from llmwiki.db.connection import connect, db_path
from llmwiki.db.migrator import Migrator

console = Console()


def init_command(
    home: Optional[Path] = typer.Option(
        None,
        "--path",
        "--home",
        help="Override the llmwiki home directory (default: ~/.llmwiki).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-run init even if the home directory already exists.",
    ),
) -> None:
    """Initialise the llmwiki data directory.

    Creates ``~/.llmwiki/`` (or the path given to ``--home``), runs the initial
    schema migration, writes the default config file, and creates the
    ``global`` workspace. Idempotent when ``--force`` is passed; otherwise
    refuses to overwrite an existing install.
    """
    target = (home or resolve_home()).expanduser().resolve()

    already_initialized = config_path(target).exists()
    if already_initialized and not force:
        console.print(
            f"[yellow]llmwiki already initialized at[/yellow] [bold]{target}[/bold]"
        )
        console.print(
            "[dim]Pass [bold]--force[/bold] to re-run init (existing files are left alone).[/dim]"
        )
        raise typer.Exit(code=1)

    target.mkdir(parents=True, exist_ok=True)
    (target / "logs").mkdir(exist_ok=True)
    (target / "crashes").mkdir(exist_ok=True)
    (target / "backups").mkdir(exist_ok=True)
    (target / "secrets").mkdir(exist_ok=True)
    (target / "workspaces").mkdir(exist_ok=True)
    (target / ".trash").mkdir(exist_ok=True)

    # Apply the schema before any workspace row is inserted.
    with connect(db_path(target)) as conn:
        applied = Migrator().apply_pending(conn)

    # Write the default config (no-op if it exists).
    cfg = Config(
        general=GeneralConfig(data_dir=str(target)),
        state=StateConfig(current_workspace=DEFAULT_WORKSPACE_SLUG),
    )
    save_config(target, cfg)

    # Create the global workspace if missing.
    global_path = target / "workspaces" / GLOBAL_SLUG
    if not global_path.exists():
        init_workspace(
            target,
            slug=GLOBAL_SLUG,
            name="Global",
            description="The user's general knowledge workspace.",
        )

    console.print(f"[green]llmwiki initialized at[/green] [bold]{target}[/bold]")
    console.print(f"[dim]Schema migrations applied: {applied or '(none — already current)'}[/dim]")
    console.print(f"[dim]Default workspace: [bold]{DEFAULT_WORKSPACE_SLUG}[/bold][/dim]")
    console.print()
    console.print("Next steps:")
    console.print("  [cyan]llmwiki status[/cyan]                  show what's set up")
    console.print("  [cyan]llmwiki project create <name>[/cyan]    create a project workspace")
    console.print("  [cyan]llmwiki paste --title ... <<< 'note'[/cyan]  capture a quick note")
