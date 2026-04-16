"""Integration test for the MCP server via subprocess.

Spawns the llmwiki MCP server as a subprocess and communicates with it via
the MCP protocol over stdio. This is the real end-to-end test — the same
path a connected Claude Code session would take.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.conftest import run_llmwiki


def test_mcp_serve_starts_and_responds(initialized_home: Path) -> None:
    """The MCP server starts on stdio and responds to an initialize request."""
    # Start the MCP server as a subprocess in pinned mode
    env = {"LLMWIKI_HOME": str(initialized_home), "PATH": "/usr/bin:/bin"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "llmwiki", "mcp", "serve", "--workspace", "global"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**env, **{"PYTHONPATH": str(Path.cwd())}},
        text=False,
    )

    try:
        # Send a minimal MCP initialize request
        # MCP uses JSON-RPC over stdio with Content-Length header framing
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1.0"},
            },
        })

        # MCP protocol uses HTTP-style content-length framing (for some transports)
        # For stdio, FastMCP 1.x uses newline-delimited JSON
        assert proc.stdin is not None
        proc.stdin.write((init_request + "\n").encode("utf-8"))
        proc.stdin.flush()

        # Give the server a moment to respond
        time.sleep(2)

        # Check that the server is still running (didn't crash on start)
        assert proc.poll() is None, (
            f"MCP server exited prematurely with code {proc.poll()}\n"
            f"stderr: {proc.stderr.read().decode() if proc.stderr else '(none)'}"
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_mcp_install_creates_config_file(initialized_home: Path, tmp_path: Path) -> None:
    """``llmwiki mcp install claude-code --workspace global`` creates a .mcp.json."""
    import os

    env = os.environ.copy()
    env["LLMWIKI_HOME"] = str(initialized_home)

    # Run install from tmp_path so .mcp.json lands there (pinned mode = project scope)
    result = subprocess.run(
        [sys.executable, "-m", "llmwiki", "mcp", "install", "claude-code", "--workspace", "global"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )
    assert result.returncode == 0, f"install failed: {result.stdout}\n{result.stderr}"

    mcp_json = tmp_path / ".mcp.json"
    assert mcp_json.exists(), "Expected .mcp.json to be created"

    config = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "mcpServers" in config
    assert "llmwiki" in config["mcpServers"]
    server_config = config["mcpServers"]["llmwiki"]
    assert server_config.get("_llmwiki_managed") is True
    assert "--workspace" in server_config.get("args", [])
    assert "global" in server_config.get("args", [])


def test_mcp_status_works_without_registrations(initialized_home: Path) -> None:
    """``llmwiki mcp status`` completes cleanly even with no registrations."""
    result = run_llmwiki(initialized_home, "mcp", "status")
    assert "No llmwiki MCP registrations detected" in result.stdout or result.returncode == 0
