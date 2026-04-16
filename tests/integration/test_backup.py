"""Integration test for ``alexandria backup create`` against real SQLite + tar."""

from __future__ import annotations

import tarfile
from pathlib import Path

from alexandria.core.backup import create_backup
from alexandria.core.workspace import init_workspace


def test_backup_includes_db_snapshot_and_workspace_files(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="research", name="Research")
    (initialized_home / "workspaces" / "research" / "raw" / "local").mkdir(parents=True)
    (initialized_home / "workspaces" / "research" / "raw" / "local" / "note.md").write_text(
        "# Test note\n\nThis is a real file.\n", encoding="utf-8"
    )
    output = initialized_home / "backups" / "test-backup.tar.gz"
    report = create_backup(initialized_home, output)

    assert report.archive_path == output
    assert output.exists()
    assert report.size_bytes > 0
    assert report.files_included > 0

    with tarfile.open(output, "r:gz") as tar:
        names = tar.getnames()

    assert any(name.endswith(".db") for name in names)
    assert any(name == "workspaces/research/raw/local/note.md" for name in names)
    assert any(name == "workspaces/global/SKILL.md" for name in names)
    assert "config.toml" in names


def test_backup_without_workspaces_still_succeeds(tmp_home: Path) -> None:
    """A backup of a barely-initialized home should still produce a valid archive."""
    tmp_home.mkdir(parents=True, exist_ok=True)
    (tmp_home / "config.toml").write_text("[general]\n", encoding="utf-8")
    output = tmp_home / "backups" / "minimal.tar.gz"
    report = create_backup(tmp_home, output)
    assert report.archive_path.exists()
    assert report.archive_path.stat().st_size > 0
