"""Sources, Alexandria calls and local-index reads shared by the SJ-marked tests."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from alexandria.core.ingest import IngestResult, ingest_file
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace
from alexandria.db.connection import connect, db_path
from alexandria.mcp.server import create_server

CODE = (
    '"""Tide tables for the field survey."""\n\n\n'
    "class TideTable:\n"
    '    """Predicted tides."""\n\n\n'
    "def predict(day):\n"
    "    return day\n"
)
CODE_QUOTE = b"Tide tables for the field survey."
NOTE = "# Tides\n\nTides rise twice a day along the survey coast.\nThe survey ran in May.\n"
NOTE_QUOTE = b"Tides rise twice a day along the survey coast."


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def workspace(home: Path) -> Path:
    return get_workspace(home, GLOBAL_SLUG).path


def ingest(home: Path, source: Path) -> IngestResult:
    """The ingest pipeline the CLI, the jobs worker and MCP ingest all run."""
    return ingest_file(home, GLOBAL_SLUG, workspace(home), source, no_merge=True)


def page_of(result: IngestResult) -> str:
    return f"wiki/{result.committed_paths[0]}"


def current_beliefs(home: Path) -> dict[str, str]:
    with connect(db_path(home)) as conn:
        rows = conn.execute(
            "SELECT belief_id, statement FROM wiki_beliefs WHERE superseded_at IS NULL"
        ).fetchall()
    return {row["belief_id"]: row["statement"] for row in rows}


def superseded_by(home: Path, belief: str) -> str | None:
    with connect(db_path(home)) as conn:
        row = conn.execute(
            "SELECT superseded_by_belief_id FROM wiki_beliefs WHERE belief_id = ?", (belief,)
        ).fetchone()
    return None if row is None else row["superseded_by_belief_id"]


def documents(home: Path) -> list[str]:
    with connect(db_path(home)) as conn:
        return [row["path"] for row in conn.execute("SELECT path FROM documents").fetchall()]


async def call(name: str, **arguments: Any) -> str:
    """Calls an Alexandria MCP tool through FastMCP's tool dispatch."""
    server = create_server(pinned_workspace=GLOBAL_SLUG)
    result = await server.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(block, "text", "") for block in content)


def added_id(text: str) -> str:
    """The belief id in belief_add's answer, `Belief added: <id> — ...`."""
    return text.split()[2]


def superseding_id(text: str) -> str:
    """The new belief id in belief_supersede's answer, `Superseded <old> with <new>`."""
    return text.split()[3]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port
