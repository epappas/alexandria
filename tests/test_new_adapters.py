"""Tests for YouTube, Notion, HuggingFace, Archive, and Folder adapters."""

import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from alexandria.core.adapters.archive import ArchiveAdapter
from alexandria.core.adapters.folder import FolderAdapter
from alexandria.core.adapters.huggingface import HuggingFaceAdapter, _fetch_readme
from alexandria.core.adapters.youtube import _extract_video_id


# --- YouTube ---

class TestYouTubeVideoId:
    def test_standard_url(self) -> None:
        assert _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert _extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_mobile_url(self) -> None:
        assert _extract_video_id("https://m.youtube.com/watch?v=abc123") == "abc123"

    def test_invalid_url(self) -> None:
        assert _extract_video_id("https://example.com/page") is None


# --- Archive ---

class TestArchiveAdapter:
    def test_zip_extraction(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create a zip with markdown files
        zip_path = tmp_path / "docs.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("readme.md", "# Hello\n\nWorld.")
            zf.writestr("notes.txt", "Some notes.")
            zf.writestr("image.png", b"\x89PNG")  # unsupported, should skip

        adapter = ArchiveAdapter()
        items, result = adapter.sync(workspace, {"path": str(zip_path)})
        assert result.items_synced == 2
        assert result.items_errored == 0

    def test_tar_extraction(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create a tar with files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "doc.md").write_text("# Doc")
        tar_path = tmp_path / "docs.tar.gz"
        with tarfile.open(str(tar_path), "w:gz") as tf:
            tf.add(str(src_dir / "doc.md"), arcname="doc.md")

        adapter = ArchiveAdapter()
        items, result = adapter.sync(workspace, {"path": str(tar_path)})
        assert result.items_synced == 1

    def test_nonexistent_archive(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        adapter = ArchiveAdapter()
        items, result = adapter.sync(workspace, {"path": "/nonexistent.zip"})
        assert len(result.errors) > 0

    def test_validate_config(self) -> None:
        adapter = ArchiveAdapter()
        assert adapter.validate_config({"path": "/some/file.zip"}) == []
        assert len(adapter.validate_config({})) > 0


# --- Folder ---

class TestFolderAdapter:
    def test_discovers_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        source = tmp_path / "project"
        source.mkdir()
        (source / "readme.md").write_text("# Project")
        (source / "config.yaml").write_text("key: value")
        sub = source / "docs"
        sub.mkdir()
        (sub / "guide.txt").write_text("Guide content")
        # Should skip .git
        git_dir = source / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("gitconfig")

        adapter = FolderAdapter()
        items, result = adapter.sync(workspace, {"path": str(source)})
        assert result.items_synced >= 3
        # .git should be skipped
        titles = [i.title for i in items]
        assert "config" not in titles or all("config.yaml" in t or "guide" in t.lower() for t in titles)

    def test_incremental_sync(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        source = tmp_path / "src"
        source.mkdir()
        (source / "file.md").write_text("v1")

        adapter = FolderAdapter()
        _, r1 = adapter.sync(workspace, {"path": str(source)})
        assert r1.items_synced == 1

        # No changes
        _, r2 = adapter.sync(workspace, {"path": str(source)})
        assert r2.items_synced == 0

        # Modify
        (source / "file.md").write_text("v2")
        _, r3 = adapter.sync(workspace, {"path": str(source)})
        assert r3.items_synced == 1

    def test_validate_config(self) -> None:
        adapter = FolderAdapter()
        assert adapter.validate_config({"path": "/some/dir"}) == []
        assert len(adapter.validate_config({})) > 0


# --- HuggingFace ---

class TestHuggingFaceAdapter:
    def test_sync_with_mock(self, tmp_path: Path, monkeypatch) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        monkeypatch.setattr(
            "alexandria.core.adapters.huggingface._fetch_readme",
            lambda repo_id: "# Model Card\n\nThis is a great model.",
        )

        adapter = HuggingFaceAdapter()
        items, result = adapter.sync(workspace, {"repos": ["org/model-name"]})
        assert result.items_synced == 1
        assert items[0].title == "org/model-name"

        # Verify file written
        files = list((workspace / "raw" / "huggingface").glob("*.md"))
        assert len(files) == 1

    def test_validate_config(self) -> None:
        adapter = HuggingFaceAdapter()
        assert adapter.validate_config({"repos": ["meta-llama/Llama-3"]}) == []
        assert len(adapter.validate_config({})) > 0
