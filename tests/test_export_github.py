"""Tests for the GitHub-format export (three-layer vault)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alexandria.core.export_github import export_github
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace
from alexandria.db.connection import connect, db_path


def _seed_workspace(ws_path: Path) -> None:
    """Drop raw + wiki files that mimic a real alexandria state."""
    raw_dir = ws_path / "raw" / "web"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "arxivorg-abs-1.md").write_text("paper body", encoding="utf-8")

    wiki_research = ws_path / "wiki" / "research"
    wiki_research.mkdir(parents=True, exist_ok=True)
    (wiki_research / "arxivorg-abs-1.md").write_text(
        "# Long Context Performance Degradation\n"
        "\n"
        "> Sources: x, 2026-04-20\n"
        "\n"
        "Summary of the long-context finding [^1].\n"
        "\n"
        "[^1]: raw/web/arxivorg-abs-1.md\n"
        "[^2]: raw/web/arxivorg-abs-1.md\n"
        "[^3]: raw/web/arxivorg-abs-1.md\n",
        encoding="utf-8",
    )

    wiki_ai = ws_path / "wiki" / "ai-security"
    wiki_ai.mkdir(parents=True, exist_ok=True)
    (wiki_ai / "episodic_memory.md").write_text(
        "# Episodic Memory\n\nCites the prior paper "
        "[arxivorg abs 1](../research/arxivorg-abs-1.md).\n",
        encoding="utf-8",
    )


def _insert_documents(conn, workspace: str) -> None:
    """Insert a raw + wiki document pair for journal rendering."""
    now = datetime.now(UTC).isoformat()
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        """INSERT INTO documents
            (id, workspace, layer, path, filename, file_type, content,
             content_hash, size_bytes, title, created_at, updated_at)
           VALUES (?, ?, 'wiki', ?, ?, 'md', ?, ?, ?, ?, ?, ?)""",
        ("doc-wiki-1", workspace, "wiki/research/arxivorg-abs-1.md",
         "arxivorg-abs-1.md", "wiki content", "hashA", 123,
         "Long Context Performance Degradation", now, now),
    )
    conn.execute(
        """INSERT INTO documents
            (id, workspace, layer, path, filename, file_type, content,
             content_hash, size_bytes, title, created_at, updated_at)
           VALUES (?, ?, 'raw', ?, ?, 'md', ?, ?, ?, ?, ?, ?)""",
        ("doc-raw-1", workspace, "raw/web/arxivorg-abs-1.md",
         "arxivorg-abs-1.md", "raw content", "hashB", 50,
         "Long Context Performance Degradation", now, now),
    )
    conn.execute("COMMIT")


def test_export_github_produces_three_layers(initialized_home: Path, tmp_path: Path) -> None:
    ws = get_workspace(initialized_home, GLOBAL_SLUG)
    _seed_workspace(ws.path)

    with connect(db_path(initialized_home)) as conn:
        _insert_documents(conn, GLOBAL_SLUG)
        result = export_github(ws.path, tmp_path / "vault", conn, GLOBAL_SLUG)

    root = tmp_path / "vault"
    assert result.files_exported == 2
    assert result.topics == 2

    # .alexandria backup present
    assert (root / ".alexandria" / "raw" / "web" / "arxivorg-abs-1.md").exists()
    assert (root / ".alexandria" / "wiki" / "research" / "arxivorg-abs-1.md").exists()

    # human wiki with title-based slugs + per-topic READMEs
    assert (root / "wiki" / "README.md").exists()
    assert (root / "wiki" / "research" / "README.md").exists()
    new_page = (root / "wiki" / "research" /
                "long-context-performance-degradation.md")
    assert new_page.exists()
    new_body = new_page.read_text(encoding="utf-8")
    # Raw link rewritten to the canonical backup
    assert "../../.alexandria/raw/web/arxivorg-abs-1.md" in new_body
    # Duplicate footnotes collapsed (3 originals → at most 1 consecutive)
    assert new_body.count("[^1]: ../../.alexandria/raw/web/arxivorg-abs-1.md") == 1

    # journal with monthly file + cross-links
    month = datetime.now(UTC).strftime("%Y-%m")
    month_file = root / "journal" / f"{month}.md"
    assert month_file.exists()
    journal_body = month_file.read_text(encoding="utf-8")
    assert "Long Context Performance Degradation" in journal_body
    assert ("../wiki/research/long-context-performance-degradation.md"
            in journal_body)
    assert "../.alexandria/raw/web/arxivorg-abs-1.md" in journal_body

    # Root README wires the whole thing together
    root_readme = (root / "README.md").read_text(encoding="utf-8")
    assert "wiki/README.md" in root_readme
    assert "journal/README.md" in root_readme
    assert ".alexandria/" in root_readme


def test_export_github_rewrites_internal_links(
    initialized_home: Path, tmp_path: Path,
) -> None:
    """Cross-topic links should point at the new title-slug filenames."""
    ws = get_workspace(initialized_home, GLOBAL_SLUG)
    _seed_workspace(ws.path)

    with connect(db_path(initialized_home)) as conn:
        _insert_documents(conn, GLOBAL_SLUG)
        export_github(ws.path, tmp_path / "vault", conn, GLOBAL_SLUG)

    ai_page = (tmp_path / "vault" / "wiki" / "ai-security" /
               "episodic-memory.md")
    assert ai_page.exists()
    body = ai_page.read_text(encoding="utf-8")
    # Old link: ../research/arxivorg-abs-1.md → new title-slug, same relative form
    assert "../research/long-context-performance-degradation.md" in body
    assert "arxivorg-abs-1.md" not in body
