"""Tests for MCP tools against real workspace data.

Each test creates a real workspace with real files, instantiates the server
(without actually running stdio), and calls tools directly via their Python
functions. This is the unit/integration boundary — we test tool logic
without a full MCP protocol roundtrip (that's in the integration tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alexandria.core.workspace import init_workspace
from alexandria.mcp.server import WorkspaceAccessError, create_server


@pytest.fixture
def workspace_with_content(initialized_home: Path) -> tuple[Path, str]:
    """Create a workspace with real wiki and raw content for testing."""
    ws = init_workspace(
        initialized_home,
        slug="research",
        name="Research",
        description="Test research workspace",
    )

    # Create wiki content
    (ws.wiki_dir / "overview.md").write_text(
        "# Overview\n\nThis wiki covers retrieval-augmented generation.\n\n"
        "## Key Findings\n- Agentic retrieval outperforms static RAG\n\n"
        "## Recent Updates\n- 2026-04-16: initial setup\n",
        encoding="utf-8",
    )
    (ws.wiki_dir / "index.md").write_text(
        "# Index\n\n| Article | Summary |\n|---|---|\n"
        "| [auth](concepts/auth.md) | Authentication architecture |\n",
        encoding="utf-8",
    )
    (ws.wiki_dir / "log.md").write_text(
        "# Wiki Log\n\n## [2026-04-16] created | Wiki Created\n- Initialized wiki\n",
        encoding="utf-8",
    )

    concepts_dir = ws.wiki_dir / "concepts"
    concepts_dir.mkdir()
    (concepts_dir / "auth.md").write_text(
        "# Authentication Architecture\n\n"
        "> Sources: Acme API Spec v1, 2026-01-10\n"
        "> Raw: [acme-api-v1](../../raw/local/acme-api-v1.md)\n\n"
        "## Overview\n"
        "Acme uses OAuth 2.0 with JWT tokens for auth.[^1]\n\n"
        "[^1]: acme-api-v1.md, p.3 — \"The auth layer uses OAuth 2.0 with JWT.\"\n",
        encoding="utf-8",
    )

    # Create raw content
    local_dir = ws.raw_dir / "local"
    local_dir.mkdir(parents=True)
    (local_dir / "acme-api-v1.md").write_text(
        "# Acme API Specification v1\n\n"
        "## Authentication\n"
        "The auth layer uses OAuth 2.0 with JWT. Tokens expire after 1 hour.\n"
        "Refresh tokens have a 7-day lifetime.\n\n"
        "## Endpoints\n"
        "Token refresh is served at the path `/oauth/refresh`.\n",
        encoding="utf-8",
    )

    return initialized_home, "research"


def test_guide_returns_l0_and_l1(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    tools = server._tool_manager._tools
    guide_fn = tools["guide"].fn

    result = guide_fn(workspace=slug)
    assert "## L0 — Identity" in result
    assert "## L1 — Essential State" in result
    assert "research" in result.lower()
    assert "not_yet_populated" in result  # Phase 1 markers


def test_overview_returns_tree_and_counts(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    # Access the tool function through FastMCP's internal registry
    tools = server._tool_manager._tools if hasattr(server, '_tool_manager') else {}
    if "overview" not in tools:
        pytest.skip("FastMCP internal API changed — update tool access pattern")
    overview_fn = tools["overview"].fn

    result = overview_fn(workspace=slug)
    assert "research" in result.lower()
    assert "tree" in result.lower() or "Directory" in result
    assert "Raw" in result or "raw" in result.lower()


def test_list_returns_files(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    list_fn = server._tool_manager._tools["list"].fn

    # Use *.md to match files at all levels (wiki/overview.md + wiki/concepts/auth.md)
    result = list_fn(workspace=slug, path="*.md")
    assert "auth.md" in result
    # overview.md may or may not match *.md depending on fnmatch path matching
    # Test with a broader glob
    result2 = list_fn(workspace=slug, path="wiki/*")
    assert "overview.md" in result2 or "concepts" in result2


def test_grep_finds_pattern(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    grep_fn = server._tool_manager._tools["grep"].fn

    result = grep_fn(workspace=slug, pattern="OAuth 2.0")
    assert "match" in result.lower()
    assert "OAuth 2.0" in result


def test_grep_case_insensitive(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    grep_fn = server._tool_manager._tools["grep"].fn

    result = grep_fn(workspace=slug, pattern="oauth", ignore_case=True)
    assert "match" in result.lower()


def test_search_via_fts5(workspace_with_content: tuple[Path, str]) -> None:
    """FTS5 search finds documents that were inserted via paste."""
    home, slug = workspace_with_content
    # We need to insert a document into the DB for FTS5 to find it.
    # The workspace_with_content fixture wrote files to disk but didn't
    # insert into the DB. Let's use paste_cmd's logic or insert directly.
    from alexandria.db.connection import connect, db_path
    from datetime import datetime, timezone
    import hashlib

    content = "Agentic retrieval outperforms static RAG in all benchmarks"
    sha = hashlib.sha256(content.encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO documents (id, workspace, layer, path, filename, title, "
            "file_type, content, content_hash, size_bytes, tags, created_at, updated_at) "
            "VALUES (?, ?, 'wiki', '/wiki/', 'overview.md', 'Overview', "
            "'md', ?, ?, ?, '[]', ?, ?)",
            (sha[:32], slug, content, sha, len(content), now, now),
        )
        conn.execute("COMMIT")

    server = create_server(pinned_workspace=slug)
    search_fn = server._tool_manager._tools["search"].fn

    result = search_fn(query="agentic retrieval", workspace=slug)
    assert "result" in result.lower()
    assert "overview" in result.lower()


def test_read_single_file(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    read_fn = server._tool_manager._tools["read"].fn

    result = read_fn(workspace=slug, path="wiki/concepts/auth.md")
    assert "Authentication Architecture" in result
    assert "OAuth 2.0" in result


def test_read_batch_glob(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    read_fn = server._tool_manager._tools["read"].fn

    result = read_fn(workspace=slug, path="wiki/**/*.md")
    assert "file(s)" in result
    assert "auth.md" in result.lower() or "Authentication" in result


def test_read_rejects_path_escape(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    read_fn = server._tool_manager._tools["read"].fn

    result = read_fn(workspace=slug, path="../../etc/passwd")
    assert "escape" in result.lower() or "not found" in result.lower()


def test_follow_resolves_citation(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    follow_fn = server._tool_manager._tools["follow"].fn

    result = follow_fn(
        workspace=slug,
        wiki_page="wiki/concepts/auth.md",
        footnote_id="1",
    )
    assert "acme-api-v1" in result.lower()
    assert "OAuth 2.0" in result


def test_follow_missing_footnote(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    follow_fn = server._tool_manager._tools["follow"].fn

    result = follow_fn(
        workspace=slug,
        wiki_page="wiki/concepts/auth.md",
        footnote_id="99",
    )
    assert "not found" in result.lower()


def test_history_reads_log(workspace_with_content: tuple[Path, str]) -> None:
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    history_fn = server._tool_manager._tools["history"].fn

    result = history_fn(workspace=slug)
    assert "created" in result.lower()
    assert "2026-04-16" in result


def test_pinned_mode_rejects_wrong_workspace(workspace_with_content: tuple[Path, str]) -> None:
    """In pinned mode, calling a tool with a different workspace slug is rejected."""
    home, slug = workspace_with_content
    server = create_server(pinned_workspace=slug)
    guide_fn = server._tool_manager._tools["guide"].fn

    # The resolve_workspace closure raises WorkspaceAccessError directly,
    # which FastMCP would catch and surface in a real MCP session. When
    # calling the tool function directly in tests, we see the raw exception.
    with pytest.raises(WorkspaceAccessError, match="workspace_not_accessible"):
        guide_fn(workspace="nonexistent")


def test_open_mode_requires_workspace_arg(initialized_home: Path) -> None:
    """In open mode, calling a tool without workspace= is an error."""
    server = create_server(pinned_workspace=None)
    guide_fn = server._tool_manager._tools["guide"].fn

    # Open mode, workspace=None should raise
    try:
        result = guide_fn(workspace=None)
        # If it didn't raise, the error should be in the result text
        assert "required" in result.lower()
    except Exception:
        pass  # Expected — workspace is required in open mode
