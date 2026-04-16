"""End-to-end integration test: init → status → project create → paste → status.

Runs the real CLI in a subprocess against a real temporary alexandria home.
No mocks. Hits real SQLite, real filesystem, real Typer.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import run_alexandria


def test_full_init_and_status_flow(tmp_home: Path) -> None:
    """The canonical Phase 0 demo script must complete cleanly."""
    # 1. status before init reports "not initialized"
    result = run_alexandria(tmp_home, "status", "--json")
    payload = json.loads(result.stdout)
    assert payload["initialized"] is False
    assert payload["schema_version"] == 0
    assert payload["workspaces"] == []

    # 2. init creates the home + global workspace + applies migrations
    run_alexandria(tmp_home, "init")
    assert (tmp_home / "config.toml").exists()
    assert (tmp_home / "state.db").exists()
    assert (tmp_home / "workspaces" / "global").is_dir()
    assert (tmp_home / "workspaces" / "global" / "raw").is_dir()
    assert (tmp_home / "workspaces" / "global" / "wiki").is_dir()
    assert (tmp_home / "workspaces" / "global" / "SKILL.md").exists()

    # 3. status after init reports the global workspace
    result = run_alexandria(tmp_home, "status", "--json")
    payload = json.loads(result.stdout)
    assert payload["initialized"] is True
    assert payload["schema_version"] >= 1
    assert payload["current_workspace"] == "global"
    assert any(w["slug"] == "global" for w in payload["workspaces"])
    assert payload["fts_integrity"]["status"] == "ok"

    # 4. workspace list shows the global workspace
    result = run_alexandria(tmp_home, "workspace", "list", "--json")
    workspaces = json.loads(result.stdout)
    assert any(w["slug"] == "global" for w in workspaces)

    # 5. project create makes a new workspace
    run_alexandria(tmp_home, "project", "create", "Research", "--description", "ML papers")
    assert (tmp_home / "workspaces" / "research").is_dir()

    result = run_alexandria(tmp_home, "project", "list", "--json")
    project_payload = json.loads(result.stdout)
    assert any(p["slug"] == "research" for p in project_payload)

    # 6. paste captures into raw/local/
    run_alexandria(
        tmp_home,
        "paste",
        "--workspace",
        "research",
        "--title",
        "test note",
        "--content",
        "this is a test note about the auth refactor",
    )
    notes = list((tmp_home / "workspaces" / "research" / "raw" / "local").glob("*.md"))
    assert len(notes) == 1
    body = notes[0].read_text(encoding="utf-8")
    assert "test note" in body.lower()

    # 7. paste with the same content is deduped (no second file)
    run_alexandria(
        tmp_home,
        "paste",
        "--workspace",
        "research",
        "--title",
        "test note",
        "--content",
        "this is a test note about the auth refactor",
    )
    notes_after = list((tmp_home / "workspaces" / "research" / "raw" / "local").glob("*.md"))
    assert len(notes_after) == 1  # unchanged

    # 8. doctor passes
    run_alexandria(tmp_home, "doctor")

    # 9. db status shows current version
    result = run_alexandria(tmp_home, "db", "status")
    assert "Schema version:" in result.stdout

    # 10. workspace use switches the current workspace
    run_alexandria(tmp_home, "workspace", "use", "research")
    result = run_alexandria(tmp_home, "workspace", "current")
    assert result.stdout.strip() == "research"


def test_lint_on_fresh_workspace_finds_no_issues(tmp_home: Path) -> None:
    """lint on a fresh workspace with no wiki pages exits cleanly."""
    run_alexandria(tmp_home, "init")
    result = run_alexandria(tmp_home, "lint", expect_exit=0)
    assert "No wiki directory" in result.stdout or "No issues" in result.stdout


def test_init_is_idempotent_with_force(tmp_home: Path) -> None:
    """``alexandria init --force`` does not error on an existing home."""
    run_alexandria(tmp_home, "init")
    run_alexandria(tmp_home, "init", "--force")
    # Workspace and config still exist and migration table is unchanged.
    assert (tmp_home / "workspaces" / "global").is_dir()


def test_init_without_force_refuses_overwrite(tmp_home: Path) -> None:
    run_alexandria(tmp_home, "init")
    run_alexandria(tmp_home, "init", expect_exit=1)
