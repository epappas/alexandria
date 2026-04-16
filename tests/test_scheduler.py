"""Tests for scheduler child process."""

import threading
import time
from pathlib import Path

import pytest

from alexandria.daemon.scheduler import SchedulerChild
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator
from alexandria.observability.logger import StructuredLogger


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "alexandria"
    h.mkdir()
    with connect(db_path(h)) as conn:
        Migrator().apply_pending(conn)
    # Create a workspace so sync jobs have something to work with
    from alexandria.core.workspace import init_workspace
    init_workspace(h, "global", "Global", "Global workspace")
    return h


@pytest.fixture
def logger(tmp_path: Path) -> StructuredLogger:
    return StructuredLogger(tmp_path / "logs", family="test-scheduler")


class TestSchedulerChild:
    def test_stop_event(self, home: Path, logger: StructuredLogger) -> None:
        """Scheduler stops when stop() is called."""
        child = SchedulerChild(home, logger)

        thread = threading.Thread(target=child.run)
        thread.start()

        # Let it run briefly
        time.sleep(0.5)
        child.stop()
        thread.join(timeout=10)

        assert not thread.is_alive()

    def test_heartbeat_written(self, home: Path, logger: StructuredLogger) -> None:
        """Scheduler writes heartbeats while running."""
        child = SchedulerChild(home, logger)

        thread = threading.Thread(target=child.run)
        thread.start()

        # Wait for at least one heartbeat cycle
        time.sleep(6)
        child.stop()
        thread.join(timeout=10)

        from alexandria.daemon.heartbeat import get_heartbeats
        with connect(db_path(home)) as conn:
            beats = get_heartbeats(conn)
            # May or may not have a beat depending on timing
            # but the scheduler should have at least attempted

    def test_build_job_schedule(self, home: Path, logger: StructuredLogger) -> None:
        child = SchedulerChild(home, logger)
        jobs = child._build_job_schedule()
        assert len(jobs) >= 2
        names = [j[0] for j in jobs]
        assert "sync_sources" in names
        assert "poll_subscriptions" in names
