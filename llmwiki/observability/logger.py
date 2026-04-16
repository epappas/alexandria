"""Structured JSONL logger for daemon and CLI operations.

Every log line is a JSON object with: ts, run_id, workspace, layer,
event, level, data. Written to per-family JSONL files under
~/.llmwiki/logs/.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Append-only JSONL logger with run_id correlation."""

    def __init__(self, log_dir: Path, family: str = "daemon") -> None:
        self._log_dir = log_dir
        self._family = family
        self._lock = threading.Lock()
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._log_dir / f"{self._family}-{date}.jsonl"

    def log(
        self,
        event: str,
        *,
        level: str = "info",
        run_id: str | None = None,
        workspace: str | None = None,
        layer: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "level": level,
            "family": self._family,
        }
        if run_id:
            entry["run_id"] = run_id
        if workspace:
            entry["workspace"] = workspace
        if layer:
            entry["layer"] = layer
        if data:
            entry["data"] = data

        line = json.dumps(entry, default=str) + "\n"
        with self._lock:
            with self._log_path().open("a", encoding="utf-8") as f:
                f.write(line)

    def info(self, event: str, **kwargs: Any) -> None:
        self.log(event, level="info", **kwargs)

    def warn(self, event: str, **kwargs: Any) -> None:
        self.log(event, level="warn", **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self.log(event, level="error", **kwargs)


_loggers: dict[str, StructuredLogger] = {}
_default_log_dir: Path | None = None


def init_logging(log_dir: Path) -> None:
    """Set the global log directory for get_logger()."""
    global _default_log_dir
    _default_log_dir = log_dir
    log_dir.mkdir(parents=True, exist_ok=True)


def get_logger(family: str = "daemon") -> StructuredLogger:
    """Get or create a logger for the given family."""
    if family not in _loggers:
        log_dir = _default_log_dir or Path.home() / ".llmwiki" / "logs"
        _loggers[family] = StructuredLogger(log_dir, family)
    return _loggers[family]
