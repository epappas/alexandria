"""Daemon parent process — supervises child processes.

Phase 6a ships a single child (scheduler). Phase 6b adds multi-child
support with adapter workers, MCP HTTP, and webhook receiver.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmwiki.daemon.heartbeat import (
    CHECK_INTERVAL,
    check_heartbeats,
    clear_heartbeats,
)
from llmwiki.daemon.scheduler import SchedulerChild
from llmwiki.db.connection import connect, db_path
from llmwiki.observability.logger import StructuredLogger, init_logging


PID_FILENAME = "daemon.pid"
MAX_RESTART_ATTEMPTS = 5
RESTART_BACKOFF_BASE = 1.0
RESTART_BACKOFF_CAP = 300.0


class DaemonParent:
    """Supervised-subprocess daemon parent."""

    def __init__(self, home: Path) -> None:
        self._home = home
        self._log_dir = home / "logs"
        self._logger = StructuredLogger(self._log_dir, family="daemon")
        self._running = False
        self._children: dict[str, multiprocessing.Process] = {}
        self._restart_counts: dict[str, int] = {}

    @property
    def pid_path(self) -> Path:
        return self._home / PID_FILENAME

    def is_running(self) -> bool:
        """Check if a daemon is already running."""
        if not self.pid_path.exists():
            return False
        try:
            pid = int(self.pid_path.read_text().strip())
            os.kill(pid, 0)  # check if process exists
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            self.pid_path.unlink(missing_ok=True)
            return False

    def start(self) -> None:
        """Start the daemon. Blocks until shutdown."""
        if self.is_running():
            raise RuntimeError("daemon is already running")

        self._write_pid()
        init_logging(self._log_dir)
        self._logger.info("daemon_starting", data={"pid": os.getpid()})

        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

        self._startup_cleanup()
        self._running = True

        try:
            self._spawn_scheduler()
            self._supervision_loop()
        finally:
            self._shutdown()

    def stop(self) -> None:
        """Signal the daemon to stop."""
        self._running = False

    def get_status(self) -> dict[str, Any]:
        """Get daemon status (can be called without the daemon running)."""
        status: dict[str, Any] = {
            "running": self.is_running(),
            "pid": None,
            "uptime": None,
            "children": [],
        }

        if self.pid_path.exists():
            try:
                status["pid"] = int(self.pid_path.read_text().strip())
            except (ValueError, FileNotFoundError):
                pass

        try:
            with connect(db_path(self._home)) as conn:
                from llmwiki.daemon.heartbeat import get_heartbeats
                status["children"] = get_heartbeats(conn)
        except Exception:
            pass

        return status

    # -- Lifecycle ----------------------------------------------------------

    def _write_pid(self) -> None:
        self._home.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()))

    def _startup_cleanup(self) -> None:
        """Orphaned-run sweep and heartbeat clear on startup."""
        self._logger.info("startup_cleanup_begin")

        with connect(db_path(self._home)) as conn:
            # Clear stale heartbeats
            clear_heartbeats(conn)

            # Sweep orphaned runs
            from llmwiki.core.runs import sweep_orphaned_runs
            swept_runs = sweep_orphaned_runs(self._home)
            if swept_runs:
                self._logger.info(
                    "orphan_sweep_runs",
                    data={"count": len(swept_runs), "ids": swept_runs[:10]},
                )

            # Sweep orphaned source_runs
            from llmwiki.core.adapters.source_repository import sweep_orphaned_source_runs
            swept_source = sweep_orphaned_source_runs(conn)
            if swept_source:
                self._logger.info(
                    "orphan_sweep_source_runs",
                    data={"count": swept_source},
                )

        self._logger.info("startup_cleanup_done")

    def _spawn_scheduler(self) -> None:
        """Spawn the scheduler child process."""
        proc = multiprocessing.Process(
            target=_run_scheduler_child,
            args=(self._home, self._log_dir),
            name="llmwiki-scheduler",
            daemon=True,
        )
        proc.start()
        self._children["scheduler"] = proc
        self._restart_counts["scheduler"] = 0
        self._logger.info(
            "child_spawned",
            data={"child": "scheduler", "pid": proc.pid},
        )

    def _supervision_loop(self) -> None:
        """Main supervision loop — check heartbeats and restart dead children."""
        while self._running:
            time.sleep(CHECK_INTERVAL)

            # Check heartbeats
            try:
                with connect(db_path(self._home)) as conn:
                    dead = check_heartbeats(conn)
                    for d in dead:
                        self._logger.warn(
                            "heartbeat_miss",
                            data=d,
                        )
            except Exception:
                pass

            # Check child processes
            for name, proc in list(self._children.items()):
                if not proc.is_alive():
                    self._logger.warn(
                        "child_died",
                        data={"child": name, "exitcode": proc.exitcode},
                    )
                    self._maybe_restart(name)

    def _maybe_restart(self, child_name: str) -> None:
        """Restart a dead child with exponential backoff."""
        count = self._restart_counts.get(child_name, 0) + 1
        self._restart_counts[child_name] = count

        if count > MAX_RESTART_ATTEMPTS:
            self._logger.error(
                "child_restart_exhausted",
                data={"child": child_name, "attempts": count},
            )
            return

        backoff = min(RESTART_BACKOFF_BASE * (2 ** (count - 1)), RESTART_BACKOFF_CAP)
        self._logger.info(
            "child_restarting",
            data={"child": child_name, "attempt": count, "backoff": backoff},
        )
        time.sleep(backoff)

        if child_name == "scheduler":
            self._spawn_scheduler()

    def _shutdown(self) -> None:
        """Gracefully stop all children and clean up."""
        self._logger.info("daemon_shutting_down")

        for name, proc in self._children.items():
            if proc.is_alive():
                self._logger.info("stopping_child", data={"child": name})
                proc.terminate()
                proc.join(timeout=10)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=5)

        self.pid_path.unlink(missing_ok=True)

        try:
            with connect(db_path(self._home)) as conn:
                clear_heartbeats(conn)
        except Exception:
            pass

        self._logger.info("daemon_stopped")

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        # No logging here — signal handlers must not acquire locks (deadlock risk)
        self.stop()


def _run_scheduler_child(home: Path, log_dir: Path) -> None:
    """Entry point for the scheduler child process."""
    logger = StructuredLogger(log_dir, family="scheduler")
    child = SchedulerChild(home, logger)
    child.run()
