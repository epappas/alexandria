"""Telegram bot runtime — thin adapter between chat and the agent.

Runs a long-polling loop: incoming message → allowlist check → agent
subprocess → reply. No webhooks, no public exposure of alexandria.

Requires the ``bot`` optional dependency: ``pip install 'alexandria-wiki[bot]'``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from alexandria.bot.agent import AgentError, ask_agent

log = logging.getLogger(__name__)


class BotRuntimeError(Exception):
    """Raised when the bot cannot be started."""


@dataclass(frozen=True)
class BotConfig:
    """Resolved runtime parameters for a Telegram session."""

    token: str
    allowlist: frozenset[int]
    workspace: str
    model: str
    max_reply_chars: int
    agent_timeout_s: int


async def run(config: BotConfig) -> None:
    """Start the Telegram long-polling loop. Blocks until the loop stops."""
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError as exc:
        raise BotRuntimeError(
            "python-telegram-bot is not installed. "
            "Install the bot extra: pip install 'alexandria-wiki[bot]'"
        ) from exc

    app = Application.builder().token(config.token).build()

    async def on_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await _handle_text(update, config)

    async def on_voice(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Voice messages aren't supported yet — send text, please.",
        )

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.VOICE, on_voice))

    log.info("Telegram bot started (allowlist size: %d)", len(config.allowlist))
    await app.run_polling()


async def _handle_text(update: object, config: BotConfig) -> None:
    """Core message handler, extracted for testability."""
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id not in config.allowlist:
        await update.message.reply_text(
            "You are not on this bot's allowlist.",
        )
        return

    question = (update.message.text or "").strip()
    if not question:
        return

    await update.message.chat.send_action("typing")
    try:
        reply = await ask_agent(
            question,
            model=config.model,
            workspace=config.workspace,
            timeout_s=config.agent_timeout_s,
            max_chars=config.max_reply_chars,
        )
    except AgentError as exc:
        await update.message.reply_text(f"Agent error: {exc}")
        return

    await update.message.reply_text(reply.text)
