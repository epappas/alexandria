"""Tests for the schema migrator against real SQLite (no mocks)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alexandria.db.connection import connect
from alexandria.db.migrator import Migration, Migrator, MigratorError


def test_discover_returns_migrations_in_order() -> None:
    """The shipped migrations directory parses cleanly and is ordered."""
    migs = Migrator().discover()
    assert len(migs) >= 1
    versions = [m.version for m in migs]
    assert versions == sorted(versions)
    assert versions[0] == 1
    assert all(isinstance(m.sha256, str) and len(m.sha256) == 64 for m in migs)


def test_apply_pending_creates_workspaces_table(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    with connect(db) as conn:
        applied = Migrator().apply_pending(conn)
        assert 1 in applied
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='workspaces'"
        )
        assert cur.fetchone() is not None


def test_apply_pending_is_idempotent_on_second_run(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    with connect(db) as conn:
        first = Migrator().apply_pending(conn)
        second = Migrator().apply_pending(conn)
    assert first  # at least one applied
    assert second == []  # nothing pending the second time


def test_user_version_matches_max_applied(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    with connect(db) as conn:
        Migrator().apply_pending(conn)
        cur = conn.execute("PRAGMA user_version")
        version = int(cur.fetchone()[0])
        max_applied = max(Migrator().applied_versions(conn).keys())
    assert version == max_applied


def test_tamper_detection_rejects_modified_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration whose on-disk sha differs from the recorded one is rejected."""
    fake_dir = tmp_path / "migs"
    fake_dir.mkdir()
    (fake_dir / "0001_initial.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    db = tmp_path / "state.db"
    migrator = Migrator(migrations_dir=fake_dir)
    with connect(db) as conn:
        migrator.apply_pending(conn)
    # Tamper: change file content after apply.
    (fake_dir / "0001_initial.sql").write_text(
        "CREATE TABLE foo (id INTEGER PRIMARY KEY, bar TEXT);", encoding="utf-8"
    )
    with connect(db) as conn:
        with pytest.raises(MigratorError, match="checksum mismatch"):
            migrator.verify_no_tampering(conn)


def test_invalid_migration_filename_is_rejected(tmp_path: Path) -> None:
    fake_dir = tmp_path / "migs"
    fake_dir.mkdir()
    (fake_dir / "wrong-name.sql").write_text("CREATE TABLE foo (id INTEGER);", encoding="utf-8")
    with pytest.raises(MigratorError, match="filename does not match"):
        Migrator(migrations_dir=fake_dir).discover()


def test_apply_failure_raises_and_does_not_record_metadata(tmp_path: Path) -> None:
    """A migration that fails leaves DDL partially applied but does NOT record
    itself in ``schema_migrations``. With IF NOT EXISTS guards, re-running
    after a fix is safe.

    Note: ``executescript()`` cannot roll back DDL atomically — a ``CREATE
    TABLE`` that succeeds before a syntax error stays in the schema. This is
    an honest trade-off documented in the architecture (``16_operations_and_reliability.md``).
    """
    fake_dir = tmp_path / "migs"
    fake_dir.mkdir()
    (fake_dir / "0001_initial.sql").write_text(
        "CREATE TABLE IF NOT EXISTS good (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (fake_dir / "0002_bad.sql").write_text(
        "CREATE TABLE IF NOT EXISTS partial (id INTEGER); INVALID SQL;",
        encoding="utf-8",
    )
    db = tmp_path / "state.db"
    migrator = Migrator(migrations_dir=fake_dir)
    with connect(db) as conn:
        with pytest.raises(MigratorError, match="bad"):
            migrator.apply_pending(conn)
    # Check: migration 1 is recorded; migration 2 is NOT recorded (metadata
    # INSERT didn't run because the DDL step failed first).
    with connect(db) as conn:
        applied = migrator.applied_versions(conn)
        assert 1 in applied
        assert 2 not in applied
        # The partial DDL from 0002 (CREATE TABLE partial) IS present —
        # executescript committed it before hitting the syntax error.
        # This is the documented trade-off: DDL is not atomic, but IF NOT
        # EXISTS guards make re-running safe.
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='partial'"
        )
        assert cur.fetchone() is not None  # partial DDL was committed
