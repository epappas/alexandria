"""``claude -p`` subprocess wrapper — the agent the bots delegate to.

The wrapper runs the Claude Code CLI in headless mode with a system
prompt that points it at the user's alexandria MCP tools. Each call
starts a fresh subprocess — no session state is preserved across
invocations (by design: each Telegram message is its own thread).
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass

from alexandria.bot.prompt import build_system_prompt


class AgentError(Exception):
    """Raised when the underlying ``claude`` subprocess fails."""


@dataclass(frozen=True)
class AgentReply:
    """What the bot sends back to the user."""

    text: str
    exit_code: int


async def ask_agent(
    question: str,
    *,
    model: str = "haiku",
    workspace: str = "",
    timeout_s: int = 180,
    max_chars: int = 3500,
) -> AgentReply:
    """Run ``claude -p`` with a system prompt that orients it at alexandria.

    Returns an ``AgentReply`` with the truncated text answer.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise AgentError(
            "claude CLI not found in PATH — install Claude Code "
            "(claude.ai/code) or set the binary path explicitly"
        )

    system = build_system_prompt(workspace=workspace)
    cmd = [
        claude_bin, "-p", "--output-format", "text",
        "--append-system-prompt", system,
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(question)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s,
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AgentError(
            f"agent timed out after {timeout_s}s"
        ) from exc

    if proc.returncode != 0:
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        raise AgentError(f"claude -p failed (exit {proc.returncode}): {err[:300]}")

    text = (stdout or b"").decode("utf-8", errors="replace").strip()
    if not text:
        text = "(the agent returned no text — try rephrasing the question)"
    if len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    return AgentReply(text=text, exit_code=proc.returncode or 0)
