"""Top-level Typer application for the ``alexandria`` CLI.

Implements the full CLI surface defined in ``docs/architecture/20_cli_surface.md``.
All commands have real implementations — no stubs.
"""

from __future__ import annotations

from typing import Optional

import typer

from alexandria import __version__
from alexandria.cli import (
    backup_cmd,
    beliefs_cmd,
    capture_cmd,
    daemon_cmd,
    db_cmd,
    doctor_cmd,
    eval_cmd,
    hooks_cmd,
    ingest_cmd,
    ingest_repo_cmd,
    init_cmd,
    lint_cmd,
    logs_cmd,
    mcp_cmd,
    paste_cmd,
    project_cmd,
    query_cmd,
    reindex_cmd,
    secrets_cmd,
    source_cmd,
    status_cmd,
    subscriptions_cmd,
    sync_cmd,
    synthesize_cmd,
    why_cmd,
    workspace_cmd,
)
from alexandria.config import resolve_home
from alexandria.core.crash_dump import install_crash_handler

app = typer.Typer(
    name="alexandria",
    help=(
        "alexandria — local-first single-user knowledge engine.\n"
        "\n"
        "Accumulates your gathered knowledge (raw sources, compiled wiki pages, "
        "event streams, AI conversations) and exposes it via MCP to connected "
        "agents like Claude Code for retroactive query and synthesis.\n"
        "\n"
        "alexandria is NOT a chat client. Interactive conversations happen in your "
        "existing MCP-capable agent (Claude Code, Cursor, Codex, ...). alexandria "
        "is the knowledge engine those agents connect to."
    ),
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)


@app.callback()
def root(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Print version and exit.",
        is_eager=True,
    ),
) -> None:
    """Top-level entry point. Installs the crash handler before any work."""
    if version:
        typer.echo(f"alexandria {__version__}")
        raise typer.Exit(code=0)
    install_crash_handler(resolve_home())


# -- Core commands -----------------------------------------------------------

app.command("init", help="Initialize ~/.alexandria/ and the global workspace.")(
    init_cmd.init_command
)
app.command("status", help="Show daemon, workspaces, and basic state.")(
    status_cmd.status_command
)
app.command("paste", help="One-shot capture from stdin into raw/local/.")(
    paste_cmd.paste_command
)
app.command("doctor", help="Run health checks across the install.")(
    doctor_cmd.doctor_command
)

# -- Workspace and project groups -------------------------------------------

workspace_app = typer.Typer(help="Workspace management.", no_args_is_help=True)
workspace_app.command("use", help="Set the current workspace.")(workspace_cmd.use_command)
workspace_app.command("current", help="Print the current workspace.")(
    workspace_cmd.current_command
)
workspace_app.command("list", help="List all workspaces.")(workspace_cmd.list_command)
app.add_typer(workspace_app, name="workspace")

project_app = typer.Typer(help="Project workspace management.", no_args_is_help=True)
project_app.command("create", help="Create a new project workspace.")(
    project_cmd.create_command
)
project_app.command("list", help="List project workspaces.")(project_cmd.list_command)
project_app.command("info", help="Show workspace state and counts.")(
    project_cmd.info_command
)
project_app.command("rename", help="Rename a workspace.")(project_cmd.rename_command)
project_app.command("delete", help="Soft-delete a workspace (moves to trash).")(
    project_cmd.delete_command
)
app.add_typer(project_app, name="project")

# -- Database group ----------------------------------------------------------

db_app = typer.Typer(help="Database operations.", no_args_is_help=True)
db_app.command("migrate", help="Apply pending schema migrations.")(db_cmd.migrate_command)
db_app.command("status", help="Show schema version and pending migrations.")(
    db_cmd.status_command
)
app.add_typer(db_app, name="db")

# -- Backup group ------------------------------------------------------------

backup_app = typer.Typer(help="Backup and restore.", no_args_is_help=True)
backup_app.command("create", help="Create a backup tarball of ~/.alexandria/.")(
    backup_cmd.create_command
)
app.add_typer(backup_app, name="backup")

# -- Reindex group -----------------------------------------------------------

reindex_app = typer.Typer(help="Rebuild SQLite indexes from filesystem.", no_args_is_help=True)
reindex_app.callback(invoke_without_command=True)(reindex_cmd.reindex_callback)
app.add_typer(reindex_app, name="reindex")

# -- Knowledge commands ------------------------------------------------------


app.command("ingest", help="Compile a source into the wiki (staged + verified).")(
    ingest_cmd.ingest_command
)

app.command("ingest-repo", help="Ingest all files from a local dir or git repo.")(
    ingest_repo_cmd.ingest_repo_command
)


app.command("query", help="Answer from the wiki by searching all knowledge sources.")(
    query_cmd.query_command
)

app.command("lint", help="Find wiki rot: stale citations, missing sources.")(
    lint_cmd.lint_command
)


app.command("why", help="Belief explainability + provenance + history (read-only).")(
    why_cmd.why_command
)

# -- Beliefs group -----------------------------------------------------------
beliefs_app = typer.Typer(help="Belief management and traceability.", no_args_is_help=True)
beliefs_app.command("list", help="List beliefs in the workspace.")(beliefs_cmd.list_command)
beliefs_app.command("history", help="Full supersession chain for a belief.")(beliefs_cmd.history_command)
beliefs_app.command("verify", help="Re-validate belief quote anchors.")(beliefs_cmd.verify_command)
beliefs_app.command("export", help="Export beliefs to JSON or CSV.")(beliefs_cmd.export_command)
app.add_typer(beliefs_app, name="beliefs")


app.command("synthesize", help="Generate temporal synthesis digest.")(
    synthesize_cmd.synthesize_command
)


app.command("sync", help="Pull from configured sources.")(
    sync_cmd.sync_command
)


# -- Source and subscription groups ------------------------------------------

source_app = typer.Typer(help="Source adapters.", no_args_is_help=True)
source_app.command("add", help="Configure a new source adapter.")(source_cmd.source_add_command)
source_app.command("list", help="List configured source adapters.")(source_cmd.source_list_command)
source_app.command("remove", help="Remove a source adapter.")(source_cmd.source_remove_command)
app.add_typer(source_app, name="source")


subscriptions_app = typer.Typer(help="Subscription inbox.", no_args_is_help=True)
subscriptions_app.command("list", help="Show pending subscription items.")(
    subscriptions_cmd.subs_list_command
)
subscriptions_app.command("show", help="Show a single subscription item.")(
    subscriptions_cmd.subs_show_command
)
subscriptions_app.command("dismiss", help="Dismiss a subscription item.")(
    subscriptions_cmd.subs_dismiss_command
)
subscriptions_app.command("poll", help="Poll subscription sources (RSS + IMAP).")(
    subscriptions_cmd.subs_poll_command
)
app.add_typer(subscriptions_app, name="subscriptions")


mcp_app = typer.Typer(help="MCP integration.", no_args_is_help=True)
mcp_app.command("serve", help="Start the stdio MCP server.")(mcp_cmd.serve_command)
mcp_app.command("serve-http", help="Start the HTTP+SSE MCP server.")(mcp_cmd.serve_http_command)
mcp_app.command("install", help="Register alexandria as an MCP server in a client.")(
    mcp_cmd.install_command
)
mcp_app.command("status", help="Show MCP server registration status.")(mcp_cmd.status_command)
app.add_typer(mcp_app, name="mcp")


eval_app = typer.Typer(help="Evaluation metrics.", no_args_is_help=True)
eval_app.command("run", help="Run evaluation metrics.")(eval_cmd.eval_run_command)
eval_app.command("report", help="Show evaluation history.")(eval_cmd.eval_report_command)
app.add_typer(eval_app, name="eval")


secrets_app = typer.Typer(help="Secret vault.", no_args_is_help=True)
secrets_app.command("set", help="Store an encrypted secret.")(secrets_cmd.secrets_set_command)
secrets_app.command("list", help="List stored secrets (metadata only).")(secrets_cmd.secrets_list_command)
secrets_app.command("rotate", help="Rotate a secret.")(secrets_cmd.secrets_rotate_command)
secrets_app.command("revoke", help="Wipe and revoke a secret.")(secrets_cmd.secrets_revoke_command)
secrets_app.command("reveal", help="Reveal a secret (audit-logged).")(secrets_cmd.secrets_reveal_command)
app.add_typer(secrets_app, name="secrets")


hooks_app = typer.Typer(help="Auto-save hooks.", no_args_is_help=True)
hooks_app.command("install", help="Install hooks into a client.")(hooks_cmd.hooks_install_command)
hooks_app.command("uninstall", help="Remove hooks from a client.")(hooks_cmd.hooks_uninstall_command)
hooks_app.command("verify", help="Verify hook installation.")(hooks_cmd.hooks_verify_command)
app.add_typer(hooks_app, name="hooks")

capture_app = typer.Typer(help="Conversation capture.", no_args_is_help=True)
capture_app.command("conversation", help="Capture a conversation transcript.")(
    capture_cmd.capture_conversation_command
)
app.command("captures", help="List captured conversations.")(capture_cmd.captures_list_command)
app.add_typer(capture_app, name="capture")


daemon_app = typer.Typer(help="Daemon management.", no_args_is_help=True)
daemon_app.command("start", help="Start the supervised-subprocess daemon.")(daemon_cmd.daemon_start_command)
daemon_app.command("stop", help="Stop the running daemon.")(daemon_cmd.daemon_stop_command)
daemon_app.command("status", help="Show daemon process state.")(daemon_cmd.daemon_status_command)
app.add_typer(daemon_app, name="daemon")

logs_app = typer.Typer(help="Structured log viewer.", no_args_is_help=True)
logs_app.command("show", help="Show structured logs.")(logs_cmd.logs_show_command)
app.add_typer(logs_app, name="logs")


def main() -> None:
    """Entry point for the ``alexandria`` console script."""
    app()


if __name__ == "__main__":
    main()
