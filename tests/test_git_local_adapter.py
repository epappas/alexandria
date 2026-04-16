"""Tests for git-local adapter using a real local git repo."""

import subprocess
from pathlib import Path

import pytest

from alexandria.core.adapters.git_local import GitLocalAdapter, GitLocalError


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real local git repo with commits."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        capture_output=True, check=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Initial commit"],
        capture_output=True, check=True,
    )

    # Create second commit
    (repo / "data.txt").write_text("some data\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "Add data file"],
        capture_output=True, check=True,
    )

    return repo


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestGitLocalAdapter:
    def test_sync_clones_and_extracts(self, git_repo, workspace_path) -> None:
        adapter = GitLocalAdapter()
        items, result = adapter.sync(
            workspace_path, {"repo_url": str(git_repo)}
        )
        assert result.items_synced == 2  # two commits
        assert result.items_errored == 0
        assert all(i.event_type == "commit" for i in items)

    def test_incremental_sync(self, git_repo, workspace_path) -> None:
        adapter = GitLocalAdapter()

        # First sync
        items1, _ = adapter.sync(workspace_path, {"repo_url": str(git_repo)})
        assert len(items1) == 2

        # Second sync with no new commits
        items2, _ = adapter.sync(workspace_path, {"repo_url": str(git_repo)})
        assert len(items2) == 0

        # Add a new commit
        (git_repo / "new.txt").write_text("new file\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(git_repo), "commit", "-m", "Third commit"],
            capture_output=True, check=True,
        )

        # Third sync should only get new commit
        items3, _ = adapter.sync(workspace_path, {"repo_url": str(git_repo)})
        assert len(items3) == 1
        assert items3[0].title == "Third commit"

    def test_git_log_static(self, git_repo) -> None:
        commits = GitLocalAdapter.git_log(git_repo, max_count=10)
        assert len(commits) == 2
        assert commits[0]["subject"] == "Add data file"

    def test_git_log_grep(self, git_repo) -> None:
        commits = GitLocalAdapter.git_log(git_repo, grep="Initial")
        assert len(commits) == 1
        assert "Initial" in commits[0]["subject"]

    def test_git_show(self, git_repo) -> None:
        commits = GitLocalAdapter.git_log(git_repo, max_count=1)
        output = GitLocalAdapter.git_show(git_repo, commits[0]["sha"])
        assert "data.txt" in output

    def test_git_blame(self, git_repo) -> None:
        output = GitLocalAdapter.git_blame(git_repo, "README.md")
        assert "Test User" in output

    def test_invalid_ref_rejected(self) -> None:
        with pytest.raises(GitLocalError, match="invalid git ref"):
            GitLocalAdapter.git_show(Path("/tmp"), "--evil")
        with pytest.raises(GitLocalError, match="invalid git ref"):
            GitLocalAdapter.git_show(Path("/tmp"), "../../etc/passwd")

    def test_validate_config(self) -> None:
        adapter = GitLocalAdapter()
        assert adapter.validate_config({"repo_url": "https://github.com/x/y"}) == []
        assert len(adapter.validate_config({})) > 0
