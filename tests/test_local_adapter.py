"""Tests for local filesystem source adapter."""

from pathlib import Path

import pytest

from llmwiki.core.adapters.local import LocalAdapter


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """Create a source directory with test files."""
    d = tmp_path / "source"
    d.mkdir()
    (d / "readme.md").write_text("# Hello\n\nThis is a test.")
    (d / "notes.txt").write_text("Some notes here.")
    (d / "data.csv").write_text("a,b,c\n1,2,3")
    return d


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestLocalAdapter:
    def test_sync_finds_md_and_txt(self, source_dir, workspace_path) -> None:
        adapter = LocalAdapter()
        items, result = adapter.sync(
            workspace_path, {"path": str(source_dir), "globs": ["*.md", "*.txt"]}
        )
        assert result.items_synced == 2
        assert result.items_errored == 0
        titles = {i.title for i in items}
        assert "readme.md" in titles
        assert "notes.txt" in titles

    def test_sync_copies_to_raw(self, source_dir, workspace_path) -> None:
        adapter = LocalAdapter()
        adapter.sync(workspace_path, {"path": str(source_dir)})
        raw_dir = workspace_path / "raw" / "local"
        assert (raw_dir / "readme.md").exists()

    def test_incremental_sync(self, source_dir, workspace_path) -> None:
        adapter = LocalAdapter()
        # First sync
        _, r1 = adapter.sync(workspace_path, {"path": str(source_dir)})
        assert r1.items_synced == 2

        # Second sync with no changes
        _, r2 = adapter.sync(workspace_path, {"path": str(source_dir)})
        assert r2.items_synced == 0

        # Modify a file
        (source_dir / "readme.md").write_text("# Updated")
        _, r3 = adapter.sync(workspace_path, {"path": str(source_dir)})
        assert r3.items_synced == 1

    def test_nonexistent_path(self, workspace_path) -> None:
        adapter = LocalAdapter()
        items, result = adapter.sync(workspace_path, {"path": "/nonexistent/path"})
        assert items == []
        assert len(result.errors) == 1

    def test_validate_config(self, source_dir) -> None:
        adapter = LocalAdapter()
        assert adapter.validate_config({"path": str(source_dir)}) == []
        assert len(adapter.validate_config({})) > 0
        assert len(adapter.validate_config({"path": "/nonexistent"})) > 0
