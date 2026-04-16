"""Integration tests for ``alexandria ingest`` — the complete write pipeline.

Tests the full flow: source file → raw copy → staged wiki page →
deterministic verifier → commit or reject. All against real filesystem
and real SQLite — no mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.core.ingest import IngestError, IngestResult, ingest_file
from alexandria.core.workspace import init_workspace
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator


@pytest.fixture
def ingest_workspace(tmp_path: Path) -> tuple[Path, Path, str]:
    """Create a full workspace ready for ingest testing."""
    home = tmp_path / "home"
    for sub in ("logs", "crashes", "backups", "secrets", "workspaces", ".trash", "runs"):
        (home / sub).mkdir(parents=True, exist_ok=True)

    with connect(db_path(home)) as conn:
        Migrator().apply_pending(conn)

    ws = init_workspace(home, slug="research", name="Research")
    return home, ws.path, "research"


@pytest.fixture
def source_with_content(tmp_path: Path) -> Path:
    """A real source file with substantial content."""
    source = tmp_path / "acme-api-v1.md"
    source.write_text(
        "# Acme API Specification v1\n\n"
        "## Authentication\n\n"
        "The auth layer uses OAuth 2.0 with JWT. Tokens expire after 1 hour.\n"
        "Refresh tokens have a 7-day lifetime.\n\n"
        "## Endpoints\n\n"
        "Token refresh is served at the path /oauth/refresh.\n"
        "The main API gateway is at api.acme.com/v1.\n",
        encoding="utf-8",
    )
    return source


def test_ingest_commits_valid_source(
    ingest_workspace: tuple[Path, Path, str],
    source_with_content: Path,
) -> None:
    """A valid source file with extractable content is ingested and committed."""
    home, ws_path, slug = ingest_workspace

    result = ingest_file(
        home=home,
        workspace_slug=slug,
        workspace_path=ws_path,
        source_file=source_with_content,
    )

    assert result.committed
    assert len(result.committed_paths) > 0
    assert result.run_id

    # The wiki page exists on disk
    for path in result.committed_paths:
        assert (ws_path / "wiki" / path).exists()

    # The source was copied to raw/
    raw_files = list((ws_path / "raw" / "local").glob("*.md"))
    assert len(raw_files) >= 1


def test_ingest_rejects_empty_source(
    ingest_workspace: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    """An empty source file raises IngestError."""
    home, ws_path, slug = ingest_workspace
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(IngestError, match="empty"):
        ingest_file(home=home, workspace_slug=slug, workspace_path=ws_path, source_file=empty)


def test_ingest_rejects_nonexistent_source(
    ingest_workspace: tuple[Path, Path, str],
) -> None:
    """A nonexistent source path raises IngestError."""
    home, ws_path, slug = ingest_workspace

    with pytest.raises(IngestError, match="not found"):
        ingest_file(
            home=home,
            workspace_slug=slug,
            workspace_path=ws_path,
            source_file=Path("/nonexistent/file.md"),
        )


def test_ingest_records_run_in_sqlite(
    ingest_workspace: tuple[Path, Path, str],
    source_with_content: Path,
) -> None:
    """The ingest run is recorded in the SQLite runs table."""
    home, ws_path, slug = ingest_workspace

    result = ingest_file(
        home=home,
        workspace_slug=slug,
        workspace_path=ws_path,
        source_file=source_with_content,
    )

    with connect(db_path(home)) as conn:
        cur = conn.execute(
            "SELECT run_id, status, run_type FROM runs WHERE run_id = ?",
            (result.run_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row["status"] == "committed"
    assert row["run_type"] == "ingest"


def test_ingest_preserves_topic_override(
    ingest_workspace: tuple[Path, Path, str],
    source_with_content: Path,
) -> None:
    """When --topic is provided, the wiki page goes under that directory."""
    home, ws_path, slug = ingest_workspace

    result = ingest_file(
        home=home,
        workspace_slug=slug,
        workspace_path=ws_path,
        source_file=source_with_content,
        topic="api-docs",
    )

    assert result.committed
    assert any("api-docs/" in p for p in result.committed_paths)


def test_ingest_cli_dry_run(
    ingest_workspace: tuple[Path, Path, str],
    source_with_content: Path,
) -> None:
    """The --dry-run flag produces a cost estimate without ingesting."""
    from tests.conftest import run_alexandria

    home, ws_path, slug = ingest_workspace

    result = run_alexandria(
        home,
        "ingest",
        str(source_with_content),
        "--workspace", slug,
        "--dry-run",
    )
    assert "Dry run" in result.stdout or "Est. cost" in result.stdout


def test_ingest_cli_end_to_end(
    ingest_workspace: tuple[Path, Path, str],
    source_with_content: Path,
) -> None:
    """Full CLI e2e: alexandria ingest <file> commits to the wiki."""
    from tests.conftest import run_alexandria

    home, ws_path, slug = ingest_workspace

    result = run_alexandria(
        home,
        "ingest",
        str(source_with_content),
        "--workspace", slug,
    )
    assert "committed" in result.stdout.lower() or "wiki/" in result.stdout
