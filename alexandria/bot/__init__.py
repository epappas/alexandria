"""Chat-bot runtimes that expose alexandria's knowledge over messaging apps.

The bots act as thin Telegram/Signal/... ↔ agent adapters: they receive a
message, spawn ``claude -p`` (which already has the alexandria MCP tools
registered), and relay the agent's answer back. alexandria itself is not
an agent — the bot is.
"""

from alexandria.bot.agent import AgentError, ask_agent

__all__ = ["AgentError", "ask_agent"]
