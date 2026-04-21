"""Tests for the bot agent subprocess wrapper.

Uses a real subprocess — we substitute ``claude`` with a stub script in
PATH rather than mocking, keeping the contract-under-test honest.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from alexandria.bot.agent import AgentError, ask_agent
from alexandria.bot.prompt import build_system_prompt


def _install_stub_claude(dir_: Path, body: str) -> None:
    """Drop a fake ``claude`` executable that echoes a canned response."""
    stub = dir_ / "claude"
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)


def test_build_system_prompt_mentions_tools() -> None:
    prompt = build_system_prompt()
    assert "mcp__alexandria__search" in prompt
    assert "Citation" in prompt or "cite" in prompt


def test_build_system_prompt_with_workspace_adds_pin_note() -> None:
    assert "workspace 'global'" in build_system_prompt(workspace="global")


def test_ask_agent_returns_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub_claude(
        tmp_path,
        "#!/usr/bin/env bash\necho 'stubbed answer with citation wiki/foo.md'\n",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH','')}")

    reply = asyncio.run(ask_agent("what do you know about foo?"))
    assert reply.exit_code == 0
    assert "stubbed answer" in reply.text


def test_ask_agent_truncates_to_max_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_claude(
        tmp_path,
        "#!/usr/bin/env bash\nprintf 'x%.0s' {1..5000}\n",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH','')}")

    reply = asyncio.run(ask_agent("q", max_chars=200))
    assert len(reply.text) == 200
    assert reply.text.endswith("...")


def test_ask_agent_raises_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_claude(
        tmp_path,
        "#!/usr/bin/env bash\necho 'rate limit reached' >&2\nexit 42\n",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH','')}")

    with pytest.raises(AgentError) as info:
        asyncio.run(ask_agent("q"))
    assert "42" in str(info.value)
    assert "rate limit" in str(info.value)


def test_ask_agent_handles_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty PATH — claude not found
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(AgentError) as info:
        asyncio.run(ask_agent("q"))
    assert "claude CLI not found" in str(info.value)


def test_ask_agent_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub_claude(
        tmp_path,
        "#!/usr/bin/env bash\nsleep 5\necho done\n",
    )
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH','')}")

    with pytest.raises(AgentError) as info:
        asyncio.run(ask_agent("q", timeout_s=1))
    assert "timed out" in str(info.value)
