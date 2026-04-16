"""MCP tools: git_log, git_show, git_blame — read-only git operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from llmwiki.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:
    @mcp.tool()
    def git_log(
        workspace: str | None = None,
        source_name: str | None = None,
        max_count: int = 50,
        grep: str | None = None,
        path_filter: str | None = None,
    ) -> str:
        """View git commit history for a cloned repository.

        Requires a git-local source to be configured and synced.
        Use ``grep`` to filter commits by message content.
        """
        repo_dir = _resolve_git_repo(workspace, source_name, resolve)
        if isinstance(repo_dir, str):
            return repo_dir

        from llmwiki.core.adapters.git_local import GitLocalAdapter
        try:
            commits = GitLocalAdapter.git_log(
                repo_dir, max_count=max_count, grep=grep, path_filter=path_filter
            )
        except Exception as exc:
            return f"git log error: {exc}"

        if not commits:
            return "No commits found."

        lines = [f"Showing {len(commits)} commit(s):\n"]
        for c in commits:
            lines.append(f"  {c['sha'][:8]} {c['date'][:10]} {c['author']}")
            lines.append(f"    {c['subject']}")
            if c.get("body"):
                lines.append(f"    {c['body'][:100]}")
        return "\n".join(lines)

    @mcp.tool()
    def git_show(
        ref: str,
        workspace: str | None = None,
        source_name: str | None = None,
    ) -> str:
        """Show a git commit or ref (diff stats)."""
        repo_dir = _resolve_git_repo(workspace, source_name, resolve)
        if isinstance(repo_dir, str):
            return repo_dir

        from llmwiki.core.adapters.git_local import GitLocalAdapter
        try:
            return GitLocalAdapter.git_show(repo_dir, ref)
        except Exception as exc:
            return f"git show error: {exc}"

    @mcp.tool()
    def git_blame(
        file_path: str,
        workspace: str | None = None,
        source_name: str | None = None,
    ) -> str:
        """Run git blame on a file in a cloned repository."""
        repo_dir = _resolve_git_repo(workspace, source_name, resolve)
        if isinstance(repo_dir, str):
            return repo_dir

        from llmwiki.core.adapters.git_local import GitLocalAdapter
        try:
            return GitLocalAdapter.git_blame(repo_dir, file_path)
        except Exception as exc:
            return f"git blame error: {exc}"


def _resolve_git_repo(
    workspace: str | None,
    source_name: str | None,
    resolve: "WorkspaceResolver",
) -> "str | Path":
    """Find the git repo directory for a workspace/source. Returns path or error string."""
    from pathlib import Path

    ws_path, slug = resolve(workspace)
    git_dir = ws_path / "raw" / "git"

    if not git_dir.is_dir():
        return f"No git repositories found in workspace {slug}."

    repos = [d for d in git_dir.iterdir() if d.is_dir() and (d / ".git").is_dir()]
    if not repos:
        return f"No cloned git repos in {slug}. Run `llmwiki sync` first."

    if source_name:
        matches = [r for r in repos if source_name in r.name]
        if not matches:
            return f"No git repo matching '{source_name}' in {slug}."
        return matches[0]

    if len(repos) == 1:
        return repos[0]

    names = ", ".join(r.name for r in repos)
    return f"Multiple git repos found: {names}. Pass source_name to select one."
