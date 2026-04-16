"""Tests for the run state machine and staged-write transaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki.core.runs import (
    Run,
    RunError,
    RunStatus,
    abandon_run,
    commit_run,
    create_run,
    get_run_path,
    get_staged_dir,
    read_run_status,
    reject_run,
    sweep_orphaned_runs,
    update_run_status,
)


def test_create_run_makes_directories(tmp_path: Path) -> None:
    run = create_run(tmp_path, "global", "test", "ingest")
    run_path = get_run_path(tmp_path, run.run_id)
    assert run_path.exists()
    assert (run_path / "staged").is_dir()
    assert (run_path / "verifier").is_dir()
    assert (run_path / "status").exists()
    assert read_run_status(tmp_path, run.run_id) == RunStatus.PENDING

    meta = json.loads((run_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["workspace"] == "global"
    assert meta["run_type"] == "ingest"


def test_commit_moves_staged_to_wiki(tmp_path: Path) -> None:
    ws_path = tmp_path / "workspace"
    (ws_path / "wiki").mkdir(parents=True)

    run = create_run(tmp_path, "global", "test", "ingest")
    staged = get_staged_dir(tmp_path, run.run_id)
    (staged / "concepts").mkdir()
    (staged / "concepts" / "auth.md").write_text("# Auth\n\nContent.\n", encoding="utf-8")

    committed = commit_run(tmp_path, run.run_id, ws_path)
    assert "concepts/auth.md" in committed
    assert (ws_path / "wiki" / "concepts" / "auth.md").exists()
    assert (ws_path / "wiki" / "concepts" / "auth.md").read_text(encoding="utf-8") == "# Auth\n\nContent.\n"
    assert read_run_status(tmp_path, run.run_id) == RunStatus.COMMITTED


def test_reject_moves_staged_to_failed(tmp_path: Path) -> None:
    run = create_run(tmp_path, "global", "test", "ingest")
    staged = get_staged_dir(tmp_path, run.run_id)
    (staged / "test.md").write_text("content", encoding="utf-8")

    reject_run(tmp_path, run.run_id, "hash mismatch on [^1]")
    assert read_run_status(tmp_path, run.run_id) == RunStatus.REJECTED
    assert not (get_run_path(tmp_path, run.run_id) / "staged").exists()
    assert (get_run_path(tmp_path, run.run_id) / "failed").exists()

    meta = json.loads((get_run_path(tmp_path, run.run_id) / "meta.json").read_text(encoding="utf-8"))
    assert meta["reject_reason"] == "hash mismatch on [^1]"


def test_abandon_transitions_pending_to_abandoned(tmp_path: Path) -> None:
    run = create_run(tmp_path, "global", "test", "ingest")
    abandon_run(tmp_path, run.run_id, "test abandon")
    assert read_run_status(tmp_path, run.run_id) == RunStatus.ABANDONED


def test_abandon_noop_on_committed(tmp_path: Path) -> None:
    ws_path = tmp_path / "workspace"
    (ws_path / "wiki").mkdir(parents=True)
    run = create_run(tmp_path, "global", "test", "ingest")
    commit_run(tmp_path, run.run_id, ws_path)
    abandon_run(tmp_path, run.run_id)  # should be a no-op
    assert read_run_status(tmp_path, run.run_id) == RunStatus.COMMITTED


def test_sweep_orphaned_runs_abandons_pending(tmp_path: Path) -> None:
    run1 = create_run(tmp_path, "global", "test", "ingest")
    run2 = create_run(tmp_path, "global", "test", "lint")
    # Manually mark run2 as committed to show sweep only touches pending
    update_run_status(tmp_path, run2.run_id, RunStatus.COMMITTED)

    swept = sweep_orphaned_runs(tmp_path)
    assert run1.run_id in swept
    assert run2.run_id not in swept
    assert read_run_status(tmp_path, run1.run_id) == RunStatus.ABANDONED
    assert read_run_status(tmp_path, run2.run_id) == RunStatus.COMMITTED


def test_wiki_untouched_on_reject(tmp_path: Path) -> None:
    """The live wiki/ is NEVER modified on a rejected run. This is the
    core invariant from 13_hostile_verifier.md — no partial writes."""
    ws_path = tmp_path / "workspace"
    wiki_dir = ws_path / "wiki" / "concepts"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "auth.md").write_text("original content", encoding="utf-8")

    run = create_run(tmp_path, "global", "test", "ingest")
    staged = get_staged_dir(tmp_path, run.run_id)
    (staged / "concepts").mkdir()
    (staged / "concepts" / "auth.md").write_text("MODIFIED content", encoding="utf-8")

    # Reject the run — the wiki should be untouched
    reject_run(tmp_path, run.run_id, "fabricated citation")

    assert (wiki_dir / "auth.md").read_text(encoding="utf-8") == "original content"
