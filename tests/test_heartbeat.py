"""Tests for daemon heartbeat management."""

import pytest

from llmwiki.daemon.heartbeat import (
    check_heartbeats,
    clear_heartbeats,
    get_heartbeats,
    record_heartbeat,
)
from llmwiki.db.connection import connect
from llmwiki.db.migrator import Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    with connect(db_path) as c:
        Migrator().apply_pending(c)
        yield c


class TestHeartbeat:
    def test_record_and_get(self, conn) -> None:
        record_heartbeat(conn, "scheduler", 1234, "running")
        beats = get_heartbeats(conn)
        assert len(beats) == 1
        assert beats[0]["child_name"] == "scheduler"
        assert beats[0]["pid"] == 1234
        assert beats[0]["state"] == "running"

    def test_upsert_updates_existing(self, conn) -> None:
        record_heartbeat(conn, "scheduler", 1234, "starting")
        record_heartbeat(conn, "scheduler", 1234, "running")
        beats = get_heartbeats(conn)
        assert len(beats) == 1
        assert beats[0]["state"] == "running"

    def test_multiple_children(self, conn) -> None:
        record_heartbeat(conn, "scheduler", 100)
        record_heartbeat(conn, "worker-1", 101)
        beats = get_heartbeats(conn)
        assert len(beats) == 2

    def test_check_heartbeats_finds_stale(self, conn) -> None:
        # Insert with an old timestamp
        conn.execute(
            "INSERT INTO daemon_heartbeats (child_name, pid, started_at, last_beat, state) "
            "VALUES ('stale', 999, '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z', 'running')"
        )
        dead = check_heartbeats(conn)
        assert len(dead) == 1
        assert dead[0]["child_name"] == "stale"

        # Check it was marked failed
        beats = get_heartbeats(conn)
        assert beats[0]["state"] == "failed"

    def test_check_heartbeats_ignores_recent(self, conn) -> None:
        record_heartbeat(conn, "fresh", 100)
        dead = check_heartbeats(conn)
        assert len(dead) == 0

    def test_check_heartbeats_ignores_already_failed(self, conn) -> None:
        conn.execute(
            "INSERT INTO daemon_heartbeats (child_name, pid, started_at, last_beat, state) "
            "VALUES ('dead', 999, '2020-01-01', '2020-01-01', 'failed')"
        )
        dead = check_heartbeats(conn)
        assert len(dead) == 0  # already failed, not re-reported

    def test_clear_heartbeats(self, conn) -> None:
        record_heartbeat(conn, "scheduler", 100)
        record_heartbeat(conn, "worker", 101)
        clear_heartbeats(conn)
        assert get_heartbeats(conn) == []
