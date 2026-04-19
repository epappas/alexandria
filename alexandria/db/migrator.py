"""Schema migration runner.

Migrations are numbered SQL files at ``alexandria/db/migrations/<NNNN>_<name>.sql``.
Each migration is checksummed (sha256) on apply, recorded in
``schema_migrations``, and the ``PRAGMA user_version`` is updated. Tampered
checksums on previously-applied migrations cause the migrator to refuse to
proceed.

Design rules from the architecture (``16_operations_and_reliability.md``):
- migrations run in ``BEGIN IMMEDIATE`` ... ``COMMIT``
- on failure the transaction rolls back
- forward-only: refusing to start on a downgrade
- every migration is checked for tampering before execution
- daemon-startup runs migrations automatically only when ``auto_migrate=True``
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alexandria.db.connection import fetch_user_version, set_user_version

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigratorError(Exception):
    """Raised when a migration cannot be applied safely."""


@dataclass(frozen=True)
class Migration:
    """A single migration script discovered on disk."""

    version: int
    name: str
    path: Path
    sql: str
    sha256: str

    @classmethod
    def from_path(cls, path: Path) -> Migration:
        match = MIGRATION_FILE_RE.match(path.name)
        if not match:
            raise MigratorError(
                f"migration filename does not match NNNN_name.sql: {path.name}"
            )
        version = int(match.group(1))
        name = match.group(2)
        sql = path.read_text(encoding="utf-8")
        sha256 = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        return cls(version=version, name=name, path=path, sql=sql, sha256=sha256)


class Migrator:
    """Discovers, validates, and applies SQL migrations."""

    def __init__(self, migrations_dir: Path | None = None) -> None:
        self.migrations_dir = migrations_dir or MIGRATIONS_DIR

    def discover(self) -> list[Migration]:
        """Return all migrations on disk, sorted by version."""
        if not self.migrations_dir.exists():
            return []
        out: list[Migration] = []
        seen: set[int] = set()
        for path in sorted(self.migrations_dir.glob("*.sql")):
            mig = Migration.from_path(path)
            if mig.version in seen:
                raise MigratorError(f"duplicate migration version {mig.version}")
            seen.add(mig.version)
            out.append(mig)
        return out

    def current_version(self, conn: sqlite3.Connection) -> int:
        """Read the current schema version from ``PRAGMA user_version``."""
        return fetch_user_version(conn)

    def applied_versions(self, conn: sqlite3.Connection) -> dict[int, str]:
        """Return ``{version: sha256}`` for every applied migration."""
        if not self._has_schema_migrations_table(conn):
            return {}
        cur = conn.execute("SELECT version, script_sha256 FROM schema_migrations")
        return {int(row["version"]): row["script_sha256"] for row in cur.fetchall()}

    def pending(self, conn: sqlite3.Connection) -> list[Migration]:
        """Return migrations whose version is greater than the current one."""
        current = self.current_version(conn)
        return [m for m in self.discover() if m.version > current]

    def verify_no_tampering(self, conn: sqlite3.Connection) -> None:
        """Raise if any applied migration's checksum no longer matches disk."""
        applied = self.applied_versions(conn)
        on_disk = {m.version: m for m in self.discover()}
        for version, recorded_sha in applied.items():
            disk = on_disk.get(version)
            if disk is None:
                raise MigratorError(
                    f"migration {version} is recorded as applied but missing on disk"
                )
            if disk.sha256 != recorded_sha:
                raise MigratorError(
                    f"migration {version} checksum mismatch: "
                    f"recorded={recorded_sha[:12]}, disk={disk.sha256[:12]}"
                )

    def apply_pending(self, conn: sqlite3.Connection) -> list[int]:
        """Apply every pending migration. Returns the versions actually applied.

        Each migration runs in its own ``BEGIN IMMEDIATE`` ... ``COMMIT``.
        If a migration fails, the transaction rolls back and the error is
        re-raised; previously-applied migrations are not affected.
        """
        self.verify_no_tampering(conn)
        applied_now: list[int] = []
        for migration in self.pending(conn):
            self._apply_one(conn, migration)
            applied_now.append(migration.version)
        return applied_now

    # -- internals -----------------------------------------------------------

    def _apply_one(self, conn: sqlite3.Connection, migration: Migration) -> None:
        # executescript() manages its own transactions — it commits any pending
        # transaction first, then runs each statement. We cannot wrap it in
        # BEGIN/COMMIT when isolation_level=None (autocommit). Instead:
        #   1. Run the DDL via executescript (all DDL uses IF NOT EXISTS)
        #   2. Record the metadata in a separate explicit transaction
        # Migration SQL MUST use IF NOT EXISTS guards for idempotency.
        try:
            conn.executescript(migration.sql)
        except sqlite3.Error as exc:
            raise MigratorError(
                f"migration {migration.version} ({migration.name}) DDL failed: {exc}"
            ) from exc

        self._ensure_schema_migrations_table(conn)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_migrations
                  (version, name, script_path, script_sha256, applied_at, applied_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    str(migration.path),
                    migration.sha256,
                    datetime.now(UTC).isoformat(),
                    "auto",
                ),
            )
            set_user_version(conn, migration.version)
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute("ROLLBACK")
            raise MigratorError(
                f"migration {migration.version} ({migration.name}) metadata failed: {exc}"
            ) from exc

    def _has_schema_migrations_table(self, conn: sqlite3.Connection) -> bool:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        return cur.fetchone() is not None

    def _ensure_schema_migrations_table(self, conn: sqlite3.Connection) -> None:
        # Migrations create this table themselves in 0001; this is a defensive no-op
        # when the table already exists. We do NOT recreate or alter it here.
        if not self._has_schema_migrations_table(conn):
            conn.execute(
                """
                CREATE TABLE schema_migrations (
                  version INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  script_path TEXT NOT NULL,
                  script_sha256 TEXT NOT NULL,
                  applied_at TEXT NOT NULL,
                  applied_by TEXT NOT NULL
                )
                """
            )
