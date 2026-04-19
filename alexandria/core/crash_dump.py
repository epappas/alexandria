"""Crash-dump handler.

Reflects mlops-engineer Finding #6 from `docs/research/reviews/plan/03_mlops_engineer.md`.
On any unhandled exception, write a structured JSON crash dump to
``<home>/crashes/<iso8601>.json`` so the user has something to attach to a bug
report. ~40 lines, ships in Phase 0 instead of Phase 11.

The crash dump never duplicates secrets — it carries command and config-path
metadata, not config values.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any


def crashes_dir(home: Path) -> Path:
    """Return the crash dump directory for a given alexandria home."""
    return home / "crashes"


def write_crash_dump(
    home: Path,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> Path:
    """Write a single crash dump file. Returns the path written."""
    crashes_dir(home).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    pid = os.getpid()
    path = crashes_dir(home) / f"{timestamp}-{pid}.json"

    payload: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "pid": pid,
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "exception_type": f"{exc_type.__module__}.{exc_type.__name__}",
        "exception_message": str(exc_value),
        "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
        "alexandria_home": str(home),
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def install_crash_handler(home: Path) -> None:
    """Install a ``sys.excepthook`` that writes a crash dump before exiting.

    The previous excepthook is preserved and called after dumping, so the
    user still sees the traceback on stderr in the normal way.
    """
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            path = write_crash_dump(home, exc_type, exc_value, exc_tb)
            print(f"\nalexandria: crash dump written to {path}", file=sys.stderr)
        except Exception as dump_err:  # never let crash-dump failure mask the real crash
            print(
                f"\nalexandria: failed to write crash dump: {dump_err}",
                file=sys.stderr,
            )
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
