"""Tests for daemon parent process."""

import os
import signal
import time
from pathlib import Path

import pytest

from llmwiki.daemon.parent import DaemonParent
from llmwiki.db.connection import connect, db_path
from llmwiki.db.migrator import Migrator


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Set up a minimal llmwiki home for daemon tests."""
    h = tmp_path / "llmwiki"
    h.mkdir()
    # Initialize DB
    with connect(db_path(h)) as conn:
        Migrator().apply_pending(conn)
    return h


class TestDaemonParent:
    def test_is_running_false_initially(self, home: Path) -> None:
        parent = DaemonParent(home)
        assert parent.is_running() is False

    def test_pid_file_management(self, home: Path) -> None:
        parent = DaemonParent(home)
        parent._write_pid()
        assert parent.pid_path.exists()
        pid = int(parent.pid_path.read_text().strip())
        assert pid == os.getpid()
        parent.pid_path.unlink()
        assert not parent.pid_path.exists()

    def test_is_running_with_stale_pid(self, home: Path) -> None:
        parent = DaemonParent(home)
        # Write a PID that doesn't exist
        parent.pid_path.write_text("999999999")
        assert parent.is_running() is False
        # Stale PID file should be cleaned up
        assert not parent.pid_path.exists()

    def test_startup_cleanup(self, home: Path) -> None:
        # Insert orphaned runs
        from llmwiki.core.runs import create_run

        run = create_run(home, "global", "cli:test", "ingest")
        # The run is in pending state

        parent = DaemonParent(home)
        parent._startup_cleanup()

        # Run should be swept to abandoned
        from llmwiki.core.runs import read_run_status, RunStatus
        status = read_run_status(home, run.run_id)
        assert status == RunStatus.ABANDONED

    def test_startup_clears_heartbeats(self, home: Path) -> None:
        from llmwiki.daemon.heartbeat import record_heartbeat, get_heartbeats

        with connect(db_path(home)) as conn:
            record_heartbeat(conn, "stale-child", 999)
            assert len(get_heartbeats(conn)) == 1

        parent = DaemonParent(home)
        parent._startup_cleanup()

        with connect(db_path(home)) as conn:
            assert len(get_heartbeats(conn)) == 0

    def test_get_status_when_not_running(self, home: Path) -> None:
        parent = DaemonParent(home)
        status = parent.get_status()
        assert status["running"] is False
        assert status["pid"] is None
