"""Tests for path traversal prevention — the AI-engineer's BLOCKER finding.

Proves that crafted ``../`` paths in source references and staged file names
cannot escape the workspace boundary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.core.citations.anchors import create_anchor, verify_quote_anchor
from llmwiki.core.runs import RunError, commit_run, create_run, get_staged_dir


def test_verify_anchor_rejects_path_traversal(tmp_path: Path) -> None:
    """A source_file with ``../`` that escapes the workspace is rejected."""
    workspace = tmp_path / "ws"
    (workspace / "raw" / "local").mkdir(parents=True)

    # Place a secret file OUTSIDE the workspace
    secret = tmp_path / "secret.md"
    secret.write_text("TOP SECRET DATA", encoding="utf-8")

    # Craft an anchor that traverses out of the workspace
    anchor = create_anchor("../secret.md", "TOP SECRET DATA")
    result = verify_quote_anchor(anchor, workspace)

    # Must NOT resolve to the secret file
    assert result.status == "source_missing", (
        f"Path traversal should be blocked, got {result.status}"
    )


def test_verify_anchor_rejects_absolute_path_traversal(tmp_path: Path) -> None:
    """An absolute path in source_file cannot escape the workspace."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    anchor = create_anchor("/etc/passwd", "root")
    result = verify_quote_anchor(anchor, workspace)
    assert result.status == "source_missing"


def test_commit_run_boundary_check_exists(tmp_path: Path) -> None:
    """commit_run validates every destination stays within wiki_dir.

    Note: Python's ``rglob("*")`` naturally only walks downward from the
    staged directory, so ``../`` files placed OUTSIDE staged/ are never
    found. The boundary check in commit_run is defense-in-depth against
    symlinks or future code paths that could produce an escaping relative
    path. This test verifies the boundary function itself works.
    """
    from llmwiki.core.runs import _is_within_boundary

    wiki = tmp_path / "wiki"
    wiki.mkdir()

    # A path inside wiki/ passes
    assert _is_within_boundary((wiki / "concepts" / "auth.md").resolve(), wiki.resolve())

    # A path outside wiki/ fails
    outside = (tmp_path / "evil.md").resolve()
    assert not _is_within_boundary(outside, wiki.resolve())


def test_commit_run_allows_normal_paths(tmp_path: Path) -> None:
    """Normal staged paths within wiki/ commit successfully."""
    home = tmp_path / "home"
    ws_path = tmp_path / "workspace"
    (ws_path / "wiki").mkdir(parents=True)

    run = create_run(home, "global", "test", "ingest")
    staged = get_staged_dir(home, run.run_id)
    (staged / "concepts").mkdir()
    (staged / "concepts" / "auth.md").write_text("# Auth\n\nContent.\n", encoding="utf-8")

    committed = commit_run(home, run.run_id, ws_path)
    assert "concepts/auth.md" in committed
    assert (ws_path / "wiki" / "concepts" / "auth.md").exists()
