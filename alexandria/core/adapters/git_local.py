"""Git-local source adapter.

Clones or fetches a git repository, then extracts commits as events.
Provides read-only git primitives (log, show, blame) for MCP tools.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alexandria.core.adapters.base import AdapterKind, FetchedItem, SyncResult


class GitLocalError(Exception):
    pass


class GitLocalAdapter:
    """Clone/fetch a git repo and extract commit events."""

    kind = AdapterKind.GIT_LOCAL

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        repo_url = config["repo_url"]
        repo_dir = self._repo_dir(workspace_path, config)
        result = SyncResult()

        # Clone or fetch
        if not (repo_dir / ".git").is_dir():
            self._clone(repo_url, repo_dir)
        else:
            self._fetch(repo_dir)

        # Get last synced commit
        state_file = repo_dir / ".alexandria_sync_state.json"
        last_sha = self._read_last_sha(state_file)

        # Extract commits
        items: list[FetchedItem] = []
        commits = self._git_log(repo_dir, since_sha=last_sha)
        # git log returns newest first; save the first (newest) sha
        latest_sha = commits[0]["sha"] if commits else None

        for commit in commits:
            items.append(FetchedItem(
                source_type="git-local",
                event_type="commit",
                title=commit["subject"],
                body=commit.get("body"),
                author=commit.get("author"),
                url=None,
                occurred_at=commit["date"],
                event_data=commit,
            ))
            result.items_synced += 1

        if latest_sha:
            self._write_last_sha(state_file, latest_sha)

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "repo_url" not in config:
            errors.append("'repo_url' is required for git-local adapter")
        return errors

    # -- Git operations (exposed for MCP tools) --------------------------------

    @staticmethod
    def git_log(
        repo_dir: Path,
        max_count: int = 50,
        grep: str | None = None,
        path_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run git log and return structured commit data."""
        cmd = [
            "git", "-C", str(repo_dir), "log",
            f"--max-count={max_count}",
            "--format=%H%x00%an%x00%aI%x00%s%x00%b%x1e",
        ]
        if grep:
            cmd.extend(["--grep", grep])
        if path_filter:
            cmd.extend(["--", path_filter])

        output = _run_git(cmd)
        return _parse_log_output(output)

    @staticmethod
    def git_show(repo_dir: Path, ref: str) -> str:
        """Run git show for a commit/ref. Returns the diff."""
        _validate_ref(ref)
        return _run_git(["git", "-C", str(repo_dir), "show", "--stat", ref])

    @staticmethod
    def git_blame(repo_dir: Path, file_path: str) -> str:
        """Run git blame on a file."""
        return _run_git(
            ["git", "-C", str(repo_dir), "blame", "--porcelain", file_path]
        )

    # -- Internals --------------------------------------------------------------

    def _repo_dir(self, workspace_path: Path, config: dict[str, Any]) -> Path:
        repo_url = config["repo_url"]
        slug = hashlib.sha256(repo_url.encode()).hexdigest()[:12]
        name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        d = workspace_path / "raw" / "git" / f"{name}-{slug}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _clone(self, url: str, dest: Path) -> None:
        _run_git(["git", "clone", "--quiet", url, str(dest)])

    def _fetch(self, repo_dir: Path) -> None:
        _run_git(["git", "-C", str(repo_dir), "fetch", "--quiet", "--all"])
        _run_git(["git", "-C", str(repo_dir), "pull", "--quiet", "--ff-only"])

    def _git_log(
        self, repo_dir: Path, since_sha: str | None = None
    ) -> list[dict[str, Any]]:
        cmd = [
            "git", "-C", str(repo_dir), "log",
            "--format=%H%x00%an%x00%aI%x00%s%x00%b%x1e",
        ]
        if since_sha:
            cmd.append(f"{since_sha}..HEAD")
        else:
            cmd.append("--max-count=200")

        output = _run_git(cmd)
        return _parse_log_output(output)

    def _read_last_sha(self, state_file: Path) -> str | None:
        if not state_file.exists():
            return None
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data.get("last_sha")

    def _write_last_sha(self, state_file: Path, sha: str) -> None:
        state_file.write_text(
            json.dumps({"last_sha": sha, "synced_at": datetime.now(UTC).isoformat()}),
            encoding="utf-8",
        )


def _validate_ref(ref: str) -> None:
    """Prevent shell injection in git refs."""
    if not ref or ref.startswith("-") or ".." in ref:
        raise GitLocalError(f"invalid git ref: {ref!r}")


def _run_git(cmd: list[str], timeout: int = 120) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitLocalError(f"git command timed out: {' '.join(cmd[:4])}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitLocalError(f"git error (exit {result.returncode}): {stderr}")
    return result.stdout


def _parse_log_output(output: str) -> list[dict[str, Any]]:
    """Parse custom git log format into structured dicts."""
    commits: list[dict[str, Any]] = []
    for entry in output.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("\x00")
        if len(parts) < 4:
            continue
        commits.append({
            "sha": parts[0].strip(),
            "author": parts[1].strip(),
            "date": parts[2].strip(),
            "subject": parts[3].strip(),
            "body": parts[4].strip() if len(parts) > 4 else "",
        })
    return commits
