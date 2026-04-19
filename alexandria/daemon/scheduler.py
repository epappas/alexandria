"""Scheduler child process for the daemon.

Runs scheduled jobs (source syncs, subscription polls) using a simple
interval-based scheduler. Each job runs in the scheduler's process.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alexandria.daemon.heartbeat import HEARTBEAT_INTERVAL, record_heartbeat
from alexandria.db.connection import connect, db_path
from alexandria.observability.logger import StructuredLogger


class SchedulerChild:
    """Single-child scheduler that runs periodic jobs."""

    def __init__(self, home: Path, logger: StructuredLogger) -> None:
        self._home = home
        self._logger = logger
        self._running = False
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Main loop. Blocks until stop() is called or SIGTERM received."""
        self._running = True
        self._logger.info("scheduler_started", data={"pid": os.getpid()})

        # Register signal handler (only works in main thread)
        try:
            signal.signal(signal.SIGTERM, self._handle_sigterm)
        except ValueError:
            pass  # not in main thread (e.g., tests)

        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        heartbeat_thread.start()

        try:
            self._job_loop()
        finally:
            self._running = False
            self._logger.info("scheduler_stopped")

    def stop(self) -> None:
        """Signal the scheduler to stop gracefully."""
        self._stop_event.set()

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        self._logger.info("scheduler_sigterm")
        self.stop()

    def _heartbeat_loop(self) -> None:
        """Write heartbeats every 5 seconds."""
        while not self._stop_event.is_set():
            try:
                with connect(db_path(self._home)) as conn:
                    record_heartbeat(conn, "scheduler", os.getpid(), "running")
            except Exception:
                pass
            self._stop_event.wait(HEARTBEAT_INTERVAL)

    def _job_loop(self) -> None:
        """Run scheduled jobs at fixed intervals."""
        # Job schedule: (name, interval_seconds, function)
        jobs = self._build_job_schedule()
        last_run: dict[str, float] = {}

        while not self._stop_event.is_set():
            now = time.monotonic()
            for name, interval, fn in jobs:
                if now - last_run.get(name, 0) >= interval:
                    self._run_job(name, fn)
                    last_run[name] = time.monotonic()

            # Sleep in short increments for responsive shutdown
            self._stop_event.wait(5.0)

    def _build_job_schedule(self) -> list[tuple[str, float, Any]]:
        """Build the list of scheduled jobs with intervals."""
        from alexandria.config import load_config
        config = load_config(self._home)

        return [
            ("sync_sources", 300.0, self._job_sync_sources),     # every 5 min
            ("poll_subscriptions", 3600.0, self._job_poll_subs),  # every 1 hour
            ("drain_captures", 60.0, self._job_drain_captures),   # every 1 min
        ]

    def _run_job(self, name: str, fn: Any) -> None:
        """Execute a single job with error handling and logging."""
        self._logger.info(f"job_started", data={"job": name})
        try:
            fn()
            self._logger.info(f"job_completed", data={"job": name})
        except Exception as exc:
            self._logger.error(
                f"job_failed", data={"job": name, "error": str(exc)}
            )

    def _job_sync_sources(self) -> None:
        """Sync all enabled source adapters."""
        from alexandria.config import load_config, resolve_workspace
        from alexandria.core.adapters.sync import run_sync
        from alexandria.core.circuit_breaker import CircuitBreakerRegistry
        from alexandria.core.ratelimit import RateLimiter, RateLimitConfig
        from alexandria.core.workspace import list_workspaces

        config = load_config(self._home)
        rate_limiter = RateLimiter()
        rate_limiter.register("github", RateLimitConfig(
            max_tokens=5000, refill_rate=5000 / 3600,
        ))
        circuit_breakers = CircuitBreakerRegistry()

        with connect(db_path(self._home)) as conn:
            workspaces = list_workspaces(self._home)
            for ws in workspaces:
                try:
                    run_sync(
                        conn=conn,
                        home=self._home,
                        workspace=ws.slug,
                        workspace_path=ws.path,
                        rate_limiter=rate_limiter,
                        circuit_breakers=circuit_breakers,
                    )
                except Exception as exc:
                    self._logger.error(
                        "sync_workspace_failed",
                        data={"workspace": ws.slug, "error": str(exc)},
                    )

    def _job_poll_subs(self) -> None:
        """Poll all subscription sources, then auto-ingest pending items."""
        from alexandria.core.adapters.subscription_poll import poll_subscriptions
        from alexandria.core.adapters.subscription_ingest import auto_ingest_pending
        from alexandria.core.workspace import list_workspaces

        with connect(db_path(self._home)) as conn:
            workspaces = list_workspaces(self._home)
            for ws in workspaces:
                try:
                    poll_subscriptions(conn, ws.slug, ws.path)
                except Exception as exc:
                    self._logger.error(
                        "poll_workspace_failed",
                        data={"workspace": ws.slug, "error": str(exc)},
                    )
                # Auto-ingest pending items from sources with auto_ingest enabled
                try:
                    report = auto_ingest_pending(
                        conn, self._home, ws.slug, ws.path, limit=10,
                    )
                    if report.ingested > 0:
                        self._logger.info(
                            "auto_ingest_completed",
                            data={"workspace": ws.slug, "ingested": report.ingested},
                        )
                except Exception as exc:
                    self._logger.error(
                        "auto_ingest_failed",
                        data={"workspace": ws.slug, "error": str(exc)},
                    )

    def _job_drain_captures(self) -> None:
        """Process pending conversation captures."""
        from alexandria.core.capture.queue import process_capture_queue
        from alexandria.core.workspace import list_workspaces

        with connect(db_path(self._home)) as conn:
            for ws in list_workspaces(self._home):
                try:
                    process_capture_queue(conn, ws.path)
                except Exception as exc:
                    self._logger.error(
                        "drain_captures_failed",
                        data={"workspace": ws.slug, "error": str(exc)},
                    )
