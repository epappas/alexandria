"""Tests for cascade operations against real filesystem."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from alexandria.core.cascade import (
    CascadeError,
    stage_hedge,
    stage_merge,
    stage_new_page,
    stage_cross_ref,
    str_replace_staged,
)


@pytest.fixture
def workspace_with_wiki(tmp_path: Path) -> tuple[Path, Path]:
    """Create a workspace with a wiki page and a staging directory."""
    ws = tmp_path / "ws"
    wiki = ws / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "## Overview\n\n"
        "Acme uses OAuth 2.0 with JWT tokens.[^1]\n\n"
        "## Endpoints\n\n"
        "The refresh endpoint is at /oauth/refresh.[^2]\n\n"
        "[^1]: acme-api-v1.md — \"The auth layer uses OAuth 2.0 with JWT.\"\n"
        "[^2]: acme-api-v1.md — \"Token refresh is served at /oauth/refresh.\"\n",
        encoding="utf-8",
    )
    (wiki / "overview.md").write_text("# Overview\n\nAuth wiki.\n", encoding="utf-8")
    (wiki / "index.md").write_text("# Index\n\n| Auth | auth concepts |\n", encoding="utf-8")

    staged = tmp_path / "staged"
    staged.mkdir()
    return ws, staged


def test_str_replace_exactly_one_match(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    shutil.copy2(ws / "wiki" / "concepts" / "auth.md", staged / "auth.md")
    str_replace_staged(
        staged / "auth.md",
        "Acme uses OAuth 2.0 with JWT tokens.",
        "Acme uses OAuth 2.0 with JWT tokens and refresh token rotation.",
    )
    content = (staged / "auth.md").read_text(encoding="utf-8")
    assert "refresh token rotation" in content


def test_str_replace_zero_match_raises(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    shutil.copy2(ws / "wiki" / "concepts" / "auth.md", staged / "auth.md")
    with pytest.raises(CascadeError, match="no match"):
        str_replace_staged(staged / "auth.md", "this text does not exist", "replacement")


def test_str_replace_multi_match_raises(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "test.md").write_text("foo bar foo bar", encoding="utf-8")
    with pytest.raises(CascadeError, match="ambiguous"):
        str_replace_staged(staged / "test.md", "foo", "baz")


def test_stage_merge_appends_to_section(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    result = stage_merge(
        staged, ws, "concepts/auth.md",
        section_heading="Overview",
        new_content="JWT rotation was added in v2.",
        footnote_line='[^3]: acme-rfc-0034.md — "JWT rotation added in v2."',
    )
    content = result.read_text(encoding="utf-8")
    assert "JWT rotation was added in v2." in content
    assert "[^3]:" in content


def test_stage_hedge_wraps_in_disputed(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    result = stage_hedge(
        staged, ws, "concepts/auth.md",
        section_heading="Endpoints",
        existing_claim_text="The refresh endpoint is at /oauth/refresh.[^2]",
        new_claim_text="The endpoint was moved to /auth/v2/refresh.",
        new_source_ref="RFC 0034",
        new_footnote_line='[^3]: acme-rfc-0034.md — "v2 moves refresh to /auth/v2/refresh."',
        date="2026-04-16",
    )
    content = result.read_text(encoding="utf-8")
    assert "::: disputed" in content
    assert "Updated 2026-04-16 per RFC 0034" in content
    assert "/auth/v2/refresh" in content
    assert "/oauth/refresh" in content  # original preserved


def test_stage_hedge_rejects_when_claim_not_found(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    with pytest.raises(CascadeError, match="existing claim not found"):
        stage_hedge(
            staged, ws, "concepts/auth.md",
            section_heading="Endpoints",
            existing_claim_text="This claim does not exist in the page.",
            new_claim_text="New claim.",
            new_source_ref="RFC 999",
            new_footnote_line="[^99]: rfc-999.md",
        )


def test_stage_new_page_creates_file(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    result = stage_new_page(
        staged,
        topic="concepts",
        slug="api-versioning",
        title="API Versioning",
        body="Acme uses semver for API versioning.",
        sources_line="Acme RFC 0034, 2026-03-15",
        raw_line="[acme-rfc-0034](../../raw/local/acme-rfc-0034.md)",
        footnotes='[^1]: acme-rfc-0034.md — "Acme uses semver."',
    )
    content = result.read_text(encoding="utf-8")
    assert "# API Versioning" in content
    assert "semver" in content
    assert "[^1]:" in content


def test_stage_new_page_refuses_duplicate(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    stage_new_page(staged, "concepts", "test", "Test", "body", "src", "raw", "")
    with pytest.raises(CascadeError, match="already exists"):
        stage_new_page(staged, "concepts", "test", "Test", "body", "src", "raw", "")


def test_stage_cross_ref_adds_see_also(workspace_with_wiki: tuple[Path, Path]) -> None:
    ws, staged = workspace_with_wiki
    result = stage_cross_ref(
        staged, ws, "concepts/auth.md", "concepts/api-versioning.md",
        label="API Versioning",
    )
    content = result.read_text(encoding="utf-8")
    assert "## See Also" in content
    assert "API Versioning" in content
