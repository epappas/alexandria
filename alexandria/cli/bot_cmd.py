"""``alexandria bot`` group — manage the Telegram chat adapter."""

from __future__ import annotations

import asyncio
import os

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace

console = Console()


def start_command(
    platform: str = typer.Option(
        "telegram", "--platform",
        help="Chat platform. Only 'telegram' is supported today.",
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", "-w",
        help="Override the configured workspace for this run.",
    ),
    model: str | None = typer.Option(
        None, "--model",
        help="Override the `claude -p` model for this run (e.g. haiku, sonnet).",
    ),
) -> None:
    """Start the chat bot. Blocks until the process is killed."""
    if platform != "telegram":
        console.print(f"[red]Unknown platform:[/red] {platform}")
        console.print("[dim]Supported: telegram[/dim]")
        raise typer.Exit(code=1)

    from alexandria.bot.telegram import BotConfig, BotRuntimeError, run

    home = resolve_home()
    config = load_config(home)
    bot_cfg = config.bot

    if not bot_cfg.telegram_allowlist:
        console.print(
            "[red]error:[/red] bot.telegram_allowlist is empty in "
            f"{home / 'config.toml'}. Add your Telegram user ID first."
        )
        raise typer.Exit(code=1)

    token = _resolve_token(home, bot_cfg.telegram_token_ref)
    if not token:
        console.print(
            "[red]error:[/red] no Telegram token available. Set via "
            "`alxia secrets set telegram_bot_token` or "
            "ALEXANDRIA_TELEGRAM_BOT_TOKEN env var."
        )
        raise typer.Exit(code=1)

    runtime_cfg = BotConfig(
        token=token,
        allowlist=frozenset(bot_cfg.telegram_allowlist),
        workspace=(workspace
                   or bot_cfg.workspace
                   or resolve_workspace(config)),
        model=model or bot_cfg.model,
        max_reply_chars=bot_cfg.max_reply_chars,
        agent_timeout_s=bot_cfg.agent_timeout_s,
    )

    console.print(
        f"[green]Telegram bot starting[/green] "
        f"(workspace: {runtime_cfg.workspace}, model: {runtime_cfg.model})"
    )
    try:
        asyncio.run(run(runtime_cfg))
    except BotRuntimeError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        console.print("[dim]Bot stopped by user.[/dim]")


def status_command() -> None:
    """Show resolved configuration and dependency availability."""
    home = resolve_home()
    config = load_config(home)
    bot_cfg = config.bot

    token_present = bool(_resolve_token(home, bot_cfg.telegram_token_ref))
    try:
        import telegram  # noqa: F401
        telegram_ok = True
    except ImportError:
        telegram_ok = False

    console.print("[bold]Bot configuration[/bold]")
    console.print("  Platform:        telegram")
    console.print(f"  Token:           {'set' if token_present else '[red]missing[/red]'}")
    console.print(f"  Token ref:       {bot_cfg.telegram_token_ref}")
    console.print(f"  Allowlist size:  {len(bot_cfg.telegram_allowlist)}")
    console.print(f"  Workspace:       {bot_cfg.workspace or '(current)'}")
    console.print(f"  Model:           {bot_cfg.model}")
    console.print(f"  Max reply chars: {bot_cfg.max_reply_chars}")
    console.print(f"  Agent timeout:   {bot_cfg.agent_timeout_s}s")
    console.print(
        f"  Dependencies:    "
        f"{'[green]python-telegram-bot installed[/green]' if telegram_ok else '[red]python-telegram-bot MISSING[/red]'}"
    )
    if not telegram_ok:
        console.print(
            "[dim]Install: pip install 'alexandria-wiki[bot]'[/dim]"
        )


def _resolve_token(home, ref: str) -> str:
    """Return the Telegram bot token from env or the secret vault."""
    env_token = os.environ.get("ALEXANDRIA_TELEGRAM_BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        from alexandria.core.secrets.vault import SecretVault
        vault = SecretVault(home)
        if vault.exists(ref):
            return vault.get(ref)
    except Exception:
        return ""
    return ""
