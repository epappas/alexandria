"""Top-level Typer application for the ``llmwiki`` CLI.

Implements the surface defined in ``docs/architecture/20_cli_surface.md``.
Phase 0 ships the commands enumerated in ``docs/IMPLEMENTATION_PLAN.md``
Phase 0; every other command is registered as a phase stub so the user can
discover the surface via ``llmwiki -h`` while honouring the no-fakes rule.
"""

from __future__ import annotations

from typing import Optional

import typer

from llmwiki import __version__
from llmwiki.cli import (
    backup_cmd,
    beliefs_cmd,
    capture_cmd,
    daemon_cmd,
    db_cmd,
    doctor_cmd,
    hooks_cmd,
    ingest_cmd,
    init_cmd,
    logs_cmd,
    mcp_cmd,
    paste_cmd,
    project_cmd,
    reindex_cmd,
    secrets_cmd,
    source_cmd,
    status_cmd,
    subscriptions_cmd,
    sync_cmd,
    why_cmd,
    workspace_cmd,
)
from llmwiki.cli._phase_stub import stub_command
from llmwiki.config import resolve_home
from llmwiki.core.crash_dump import install_crash_handler

app = typer.Typer(
    name="llmwiki",
    help=(
        "llmwiki — local-first single-user knowledge engine.\n"
        "\n"
        "Accumulates your gathered knowledge (raw sources, compiled wiki pages, "
        "event streams, AI conversations) and exposes it via MCP to connected "
        "agents like Claude Code for retroactive query and synthesis.\n"
        "\n"
        "llmwiki is NOT a chat client. Interactive conversations happen in your "
        "existing MCP-capable agent (Claude Code, Cursor, Codex, ...). llmwiki "
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
        typer.echo(f"llmwiki {__version__}")
        raise typer.Exit(code=0)
    install_crash_handler(resolve_home())


# -- Phase 0 commands (real implementations) --------------------------------

app.command("init", help="Initialize ~/.llmwiki/ and the global workspace.")(
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

# -- Backup group (mlops F3 — moved to Phase 0) -----------------------------

backup_app = typer.Typer(help="Backup and restore.", no_args_is_help=True)
backup_app.command("create", help="Create a backup tarball of ~/.llmwiki/.")(
    backup_cmd.create_command
)
app.add_typer(backup_app, name="backup")

# -- Reindex group (mlops F4 — fts-verify in Phase 0) -----------------------

reindex_app = typer.Typer(help="Rebuild SQLite indexes from filesystem.", no_args_is_help=True)
reindex_app.callback(invoke_without_command=True)(reindex_cmd.reindex_callback)
app.add_typer(reindex_app, name="reindex")

# -- Stubs for commands shipped in later phases -----------------------------


app.command("ingest", help="Compile a source into the wiki (staged + verified).")(
    ingest_cmd.ingest_command
)


@app.command("query", help="Answer from the wiki (Phase 1+).")
def _query_stub(
    question: str = typer.Argument(..., help="The question to answer."),
) -> None:
    stub_command(1, "llmwiki query", "synthesize an answer from the wiki via the agent loop")


@app.command("lint", help="Find wiki rot (Phase 2+).")
def _lint_stub() -> None:
    stub_command(2, "llmwiki lint", "auto-fix deterministic issues; verifier reports heuristic")


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


@app.command("synthesize", help="Trigger temporal synthesis (Phase 8).")
def _synthesize_stub() -> None:
    stub_command(8, "llmwiki synthesize", "run scheduled temporal synthesis from event streams")


app.command("sync", help="Pull from configured sources.")(
    sync_cmd.sync_command
)


# -- Stub command groups for later phases -----------------------------------

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
mcp_app.command("install", help="Register llmwiki as an MCP server in a client.")(
    mcp_cmd.install_command
)
mcp_app.command("status", help="Show MCP server registration status.")(mcp_cmd.status_command)
app.add_typer(mcp_app, name="mcp")


eval_app = typer.Typer(help="Evaluation metrics (Phase 9).", no_args_is_help=True)


@eval_app.command("run")
def _eval_run_stub(
    metric: str = typer.Option("all", "--metric", help="Metric name (M1..M5 or all)."),
) -> None:
    stub_command(9, "llmwiki eval run", "compute one or all of the M1-M5 metrics")


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
    """Entry point for the ``llmwiki`` console script."""
    app()


if __name__ == "__main__":
    main()
