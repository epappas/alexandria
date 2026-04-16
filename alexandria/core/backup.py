"""Backup helpers.

Reflects mlops-engineer Finding #3 from `docs/research/reviews/plan/03_mlops_engineer.md`.
Phase 0 ships a minimum viable backup primitive — a SQLite ``VACUUM INTO``
plus a tar archive of the rest of the alexandria home — so users have a safe
recovery path long before the full restore-with-verification story arrives in
Phase 11.

Design rules:
- The SQLite snapshot uses ``VACUUM INTO`` (a single sqlite call) so the file
  is consistent even if the daemon is running and writing.
- The tar archive contains the SQLite snapshot plus workspaces/, secrets/
  (still encrypted), and config.toml. It does NOT contain log files, .trash/,
  or runs/ — those are not part of the durable state.
- The output filename is timestamped if not provided.
- The archive is written to a ``.tmp`` then renamed for atomicity.
"""

from __future__ import annotations

import sqlite3
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from alexandria.db.connection import db_path


@dataclass(frozen=True)
class BackupReport:
    """Result of a backup creation."""

    archive_path: Path
    size_bytes: int
    db_snapshot_path: Path
    files_included: int


class BackupError(Exception):
    """Raised when a backup cannot be created safely."""


def default_backup_filename() -> str:
    """Return a timestamped backup archive filename."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"alexandria-backup-{ts}.tar.gz"


def create_backup(home: Path, output: Path | None = None) -> BackupReport:
    """Create a backup tar.gz of the alexandria home.

    Steps:
    1. ``VACUUM INTO`` the live SQLite into ``<home>/backups/snapshot-<ts>.db``.
    2. Tar (gzip) the snapshot + workspaces/ + secrets/ + config.toml into the
       output path.
    3. Return a structured report.
    """
    if not home.exists():
        raise BackupError(f"alexandria home does not exist: {home}")

    backups_dir = home / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    output_path = output or (backups_dir / default_backup_filename())
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot the database via VACUUM INTO.
    snapshot_path = _snapshot_sqlite(home, backups_dir)

    # 2. Build the tar.gz archive.
    tmp_archive = output_path.with_suffix(output_path.suffix + ".tmp")
    files_included = 0
    try:
        with tarfile.open(tmp_archive, "w:gz") as tar:
            files_included += _tar_add(tar, snapshot_path, arcname=f"db/{snapshot_path.name}")
            workspaces = home / "workspaces"
            if workspaces.exists():
                files_included += _tar_add_tree(tar, workspaces, arcname_root="workspaces")
            secrets = home / "secrets"
            if secrets.exists():
                files_included += _tar_add_tree(tar, secrets, arcname_root="secrets")
            config = home / "config.toml"
            if config.exists():
                files_included += _tar_add(tar, config, arcname="config.toml")
        tmp_archive.replace(output_path)
    except Exception:
        if tmp_archive.exists():
            tmp_archive.unlink()
        raise

    return BackupReport(
        archive_path=output_path,
        size_bytes=output_path.stat().st_size,
        db_snapshot_path=snapshot_path,
        files_included=files_included,
    )


def _snapshot_sqlite(home: Path, backups_dir: Path) -> Path:
    """Run ``VACUUM INTO`` on the live database to a backups subdirectory."""
    live = db_path(home)
    if not live.exists():
        # Empty install — no DB to snapshot. Return a placeholder marker file.
        marker = backups_dir / "no-database.txt"
        marker.write_text(
            "No SQLite database existed at backup time.\n"
            f"Expected at: {live}\n",
            encoding="utf-8",
        )
        return marker

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = backups_dir / f"snapshot-{ts}.db"
    if snapshot.exists():
        snapshot.unlink()

    src = sqlite3.connect(live, timeout=5.0)
    try:
        src.execute("PRAGMA journal_mode = WAL")
        # VACUUM INTO requires the destination not to exist.
        src.execute(f"VACUUM INTO '{snapshot.as_posix()}'")
    finally:
        src.close()
    return snapshot


def _tar_add(tar: tarfile.TarFile, path: Path, arcname: str) -> int:
    tar.add(path, arcname=arcname)
    return 1


def _tar_add_tree(tar: tarfile.TarFile, root: Path, arcname_root: str) -> int:
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root)
            tar.add(path, arcname=f"{arcname_root}/{rel.as_posix()}")
            count += 1
    return count
