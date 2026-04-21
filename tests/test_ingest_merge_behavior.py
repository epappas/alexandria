"""Tests for cascade merge behavior fixes: per-source section headings + no_merge flag."""

from __future__ import annotations

from pathlib import Path

from alexandria.core.ingest import _per_source_section_heading, ingest_file
from alexandria.core.workspace import GLOBAL_SLUG, get_workspace


def _write_source(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def test_per_source_section_heading_uses_title() -> None:
    assert _per_source_section_heading("Machine-speed asymmetry", "04-ms") == (
        "From: Machine-speed asymmetry"
    )


def test_per_source_section_heading_falls_back_to_slug() -> None:
    assert _per_source_section_heading("", "url-slug") == "From: url-slug"
    assert _per_source_section_heading("   ", "url-slug") == "From: url-slug"


def test_per_source_section_heading_truncates_long_titles() -> None:
    long_title = "A" * 200
    heading = _per_source_section_heading(long_title, "s")
    assert heading.startswith("From: ")
    # "From: " (6) + content (<= 80) = <= 86
    assert len(heading) <= 86
    assert heading.endswith("...")


def test_no_merge_forces_new_page_even_when_related(
    initialized_home: Path, tmp_path: Path,
) -> None:
    """With no_merge=True, ingesting a second related source creates a new
    wiki page instead of merging into the first."""
    ws = get_workspace(initialized_home, GLOBAL_SLUG)

    # First ingest establishes a page
    src_a = tmp_path / "note_a.md"
    _write_source(
        src_a, "Machine-Speed Asymmetry Research",
        "Attackers operate at machine speed while defenders are human-paced. " * 5,
    )
    ingest_file(
        home=initialized_home, workspace_slug=GLOBAL_SLUG,
        workspace_path=ws.path, source_file=src_a,
    )

    # Second source with the same theme — cascade *might* want to merge
    src_b = tmp_path / "note_b.md"
    _write_source(
        src_b, "Machine-Speed Asymmetry in Defense",
        "Defenders need machine-speed response. " * 5,
    )
    result = ingest_file(
        home=initialized_home, workspace_slug=GLOBAL_SLUG,
        workspace_path=ws.path, source_file=src_b,
        no_merge=True,
    )

    # With no_merge, result.committed_paths should contain a distinct new
    # wiki page rather than merging into note_a.md's page.
    assert result.committed
    assert len(result.committed_paths) == 1
    new_page = result.committed_paths[0]
    # The slug is derived from source_file stem = "note_b"; a fresh page exists
    assert new_page.endswith("note_b.md") or "note-b" in new_page
    # Both source pages should exist in wiki/ (second didn't merge into first)
    wiki_files = list((ws.path / "wiki").rglob("*.md"))
    wiki_names = {p.stem for p in wiki_files}
    assert "note_a" in wiki_names or "note-a" in wiki_names
    assert "note_b" in wiki_names or "note-b" in wiki_names
