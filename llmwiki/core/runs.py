"""Run state machine for staged-write transactions.

Per ``13_hostile_verifier.md``, every wiki write is wrapped in a run with
exactly five states: pending → verifying → committed | rejected | abandoned.

The run also manages the on-disk staging directory:
``~/.llmwiki/runs/<run_id>/{meta.json, plan.json, staged/, verifier/, status}``
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class RunStatus(str, Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    COMMITTED = "committed"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


class RunError(Exception):
    """Raised on invalid state transitions or run operations."""


@dataclass
class Run:
    """A single staged-write transaction."""

    run_id: str
    workspace: str
    triggered_by: str
    run_type: str
    status: RunStatus = RunStatus.PENDING
    started_at: str = ""
    ended_at: str | None = None
    verdict: str | None = None
    reject_reason: str | None = None
    loop_count: int = 1
    parent_run_id: str | None = None
    anchor_format_version: int = 1

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    """Generate a unique run ID: date prefix + short UUID."""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:12]
    return f"{date}-{short}"


def runs_dir(home: Path) -> Path:
    """Return the directory that holds all run staging directories."""
    d = home / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_run(
    home: Path,
    workspace: str,
    triggered_by: str,
    run_type: str,
) -> Run:
    """Create a new run with its on-disk staging directory."""
    run = Run(
        run_id=generate_run_id(),
        workspace=workspace,
        triggered_by=triggered_by,
        run_type=run_type,
    )

    run_path = runs_dir(home) / run.run_id
    run_path.mkdir(parents=True)
    (run_path / "staged").mkdir()
    (run_path / "verifier").mkdir()
    (run_path / "status").write_text(run.status.value, encoding="utf-8")
    (run_path / "meta.json").write_text(
        json.dumps(
            {
                "run_id": run.run_id,
                "workspace": run.workspace,
                "triggered_by": run.triggered_by,
                "run_type": run.run_type,
                "started_at": run.started_at,
                "anchor_format_version": run.anchor_format_version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return run


def get_run_path(home: Path, run_id: str) -> Path:
    """Return the path to a run's staging directory."""
    return runs_dir(home) / run_id


def get_staged_dir(home: Path, run_id: str) -> Path:
    """Return the staged/ directory inside a run."""
    return get_run_path(home, run_id) / "staged"


def read_run_status(home: Path, run_id: str) -> RunStatus:
    """Read the current status of a run from disk."""
    status_file = get_run_path(home, run_id) / "status"
    if not status_file.exists():
        raise RunError(f"run {run_id} not found")
    return RunStatus(status_file.read_text(encoding="utf-8").strip())


def update_run_status(home: Path, run_id: str, new_status: RunStatus) -> None:
    """Write a new status to disk."""
    status_file = get_run_path(home, run_id) / "status"
    status_file.write_text(new_status.value, encoding="utf-8")


def commit_run(home: Path, run_id: str, workspace_path: Path) -> list[str]:
    """Atomically move staged files into the live wiki/ directory.

    Returns the list of relative paths that were committed.
    """
    staged = get_staged_dir(home, run_id)
    if not staged.exists():
        raise RunError(f"staged directory not found for run {run_id}")

    committed_paths: list[str] = []
    wiki_dir = workspace_path / "wiki"

    for src_file in sorted(staged.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(staged)
        dest = wiki_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_file), str(dest))
        committed_paths.append(str(rel))

    update_run_status(home, run_id, RunStatus.COMMITTED)

    # Write final metadata
    meta_path = get_run_path(home, run_id) / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
    meta["status"] = "committed"
    meta["committed_paths"] = committed_paths
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return committed_paths


def reject_run(home: Path, run_id: str, reason: str) -> None:
    """Move a run to rejected status and move staging to failed/."""
    update_run_status(home, run_id, RunStatus.REJECTED)
    run_path = get_run_path(home, run_id)

    failed_dir = run_path / "failed"
    staged = run_path / "staged"
    if staged.exists():
        shutil.move(str(staged), str(failed_dir))

    meta_path = run_path / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["ended_at"] = datetime.now(timezone.utc).isoformat()
    meta["status"] = "rejected"
    meta["reject_reason"] = reason
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def abandon_run(home: Path, run_id: str, reason: str = "daemon restart") -> None:
    """Transition a pending/verifying run to abandoned."""
    current = read_run_status(home, run_id)
    if current not in (RunStatus.PENDING, RunStatus.VERIFYING):
        return
    update_run_status(home, run_id, RunStatus.ABANDONED)

    run_path = get_run_path(home, run_id)
    staged = run_path / "staged"
    if staged.exists():
        failed = run_path / "failed"
        shutil.move(str(staged), str(failed))

    meta_path = run_path / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["ended_at"] = datetime.now(timezone.utc).isoformat()
        meta["status"] = "abandoned"
        meta["reject_reason"] = reason
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def sweep_orphaned_runs(home: Path) -> list[str]:
    """Transition all pending/verifying runs to abandoned.

    Called on daemon startup (or any CLI that needs a clean state).
    Returns the list of run_ids that were swept.
    """
    swept: list[str] = []
    rdir = runs_dir(home)
    if not rdir.exists():
        return swept
    for run_path in sorted(rdir.iterdir()):
        if not run_path.is_dir():
            continue
        status_file = run_path / "status"
        if not status_file.exists():
            continue
        status = status_file.read_text(encoding="utf-8").strip()
        if status in ("pending", "verifying"):
            abandon_run(home, run_path.name, reason="orphan sweep")
            swept.append(run_path.name)
    return swept


def insert_run_row(conn: Any, run: Run) -> None:
    """Insert a run row into the SQLite runs table."""
    conn.execute(
        """
        INSERT INTO runs
          (run_id, workspace, triggered_by, run_type, status, started_at,
           anchor_format_version, parent_run_id, loop_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_id,
            run.workspace,
            run.triggered_by,
            run.run_type,
            run.status.value,
            run.started_at,
            run.anchor_format_version,
            run.parent_run_id,
            run.loop_count,
        ),
    )


def update_run_row(conn: Any, run_id: str, **fields: Any) -> None:
    """Update specific fields on a run row."""
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [run_id]
    conn.execute(f"UPDATE runs SET {set_clause} WHERE run_id = ?", values)
