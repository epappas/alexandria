"""``history`` — structured query over wiki log entries and runs.

In Phase 1 this reads ``wiki/log.md`` from disk (the wiki_log_entries table
and the runs table arrive in Phase 2+). Returns parsed log entries.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver

LOG_ENTRY_RE = re.compile(
    r"^## \[(\d{4}-\d{2}-\d{2})\] (\w+) \| (.+)$", re.MULTILINE
)


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:

    @mcp.tool(
        name="history",
        description=(
            "Query the workspace's operation history. "
            "In Phase 1, reads from wiki/log.md. In Phase 2+, this also "
            "queries the structured wiki_log_entries and runs tables. "
            "Filter by operation type (ingest/query/lint) and date range."
        ),
    )
    def history(
        workspace: str | None = None,
        op: str | None = None,
        since: str | None = None,
        limit: int = 30,
    ) -> str:
        ws_path, slug = resolve(workspace)

        log_path = ws_path / "wiki" / "log.md"
        if not log_path.exists():
            return (
                f"No log entries yet in workspace `{slug}`. "
                f"The log is populated when ingest, query, or lint operations "
                f"run (Phase 2+)."
            )

        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"error reading log: {exc}"

        entries = _parse_log(text)

        if op:
            entries = [e for e in entries if e["op"] == op]
        if since:
            entries = [e for e in entries if e["date"] >= since]

        entries = entries[-limit:]

        if not entries:
            filter_desc = ""
            if op:
                filter_desc += f" op={op}"
            if since:
                filter_desc += f" since={since}"
            return f"No log entries matching{filter_desc} in workspace `{slug}`."

        lines = [f"**{len(entries)} log entry/entries** in `{slug}`:\n"]
        for entry in entries:
            lines.append(
                f"- **[{entry['date']}]** `{entry['op']}` | {entry['title']}"
            )
            if entry["details"]:
                for detail in entry["details"][:5]:
                    lines.append(f"  {detail}")

        # Phase marker
        lines.append(
            "\n*Note: structured run history (runs table, verifier verdicts) "
            "arrives in Phase 2.*"
        )

        return "\n".join(lines)


def _parse_log(text: str) -> list[dict[str, object]]:
    """Parse wiki/log.md into structured entries."""
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in text.split("\n"):
        match = LOG_ENTRY_RE.match(line)
        if match:
            if current is not None:
                entries.append(current)
            current = {
                "date": match.group(1),
                "op": match.group(2),
                "title": match.group(3),
                "details": [],
            }
        elif current is not None and line.startswith("- "):
            assert isinstance(current["details"], list)
            current["details"].append(line)

    if current is not None:
        entries.append(current)

    return entries
