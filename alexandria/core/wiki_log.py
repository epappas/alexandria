"""Wiki operation log — append-only journal of what Alexandria did.

Every ingest, query, lint, and sync appends an entry to wiki/log.md.
The guide tool reads this to show recent activity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def append_log_entry(
    workspace_path: Path,
    operation: str,
    summary: str,
    *,
    run_id: str = "",
) -> None:
    """Append a timestamped entry to wiki/log.md."""
    log_path = workspace_path / "wiki" / "log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d %H:%M")
    run_ref = f" (run {run_id})" if run_id else ""

    entry = f"## [{date_str}] {operation}{run_ref}\n- {summary}\n\n"

    if not log_path.exists():
        log_path.write_text(f"# Wiki Log\n\n{entry}", encoding="utf-8")
    else:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
