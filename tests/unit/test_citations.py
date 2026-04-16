"""Tests for citation extraction and quote-anchor verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.core.citations import (
    AnchorVerifyResult,
    Footnote,
    QuoteAnchor,
    compute_quote_hash,
    extract_footnotes,
    verify_quote_anchor,
)
from llmwiki.core.citations.anchors import create_anchor


SAMPLE_PAGE = """\
# Authentication Architecture

Acme uses OAuth 2.0 with JWT tokens for auth.[^1]
The refresh endpoint is at /oauth/refresh.[^2]

[^1]: acme-api-v1.md, p.3 — "The auth layer uses OAuth 2.0 with JWT."
[^2]: acme-api-v1.md, p.12 — "Token refresh is served at the path /oauth/refresh."
"""


def test_extract_footnotes_parses_both() -> None:
    footnotes = extract_footnotes(SAMPLE_PAGE)
    assert len(footnotes) == 2
    assert footnotes[0].footnote_id == "1"
    assert footnotes[0].source_file == "acme-api-v1.md"
    assert footnotes[0].page_hint == 3
    assert footnotes[0].quote == "The auth layer uses OAuth 2.0 with JWT."
    assert footnotes[1].footnote_id == "2"
    assert footnotes[1].page_hint == 12


def test_extract_footnotes_no_quote() -> None:
    text = "[^1]: some-source.md, p.5\n"
    footnotes = extract_footnotes(text)
    assert len(footnotes) == 1
    assert footnotes[0].quote is None
    assert not footnotes[0].has_quote


def test_compute_quote_hash_is_deterministic() -> None:
    quote = "The auth layer uses OAuth 2.0 with JWT."
    h1 = compute_quote_hash(quote)
    h2 = compute_quote_hash(quote)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_compute_quote_hash_strips_whitespace() -> None:
    assert compute_quote_hash("  hello  ") == compute_quote_hash("hello")


def test_create_anchor_finds_offset() -> None:
    source = "prefix text The auth layer uses OAuth 2.0 with JWT. suffix text"
    anchor = create_anchor("source.md", "The auth layer uses OAuth 2.0 with JWT.", source)
    assert anchor.offset == 12
    assert anchor.quote_hash == compute_quote_hash("The auth layer uses OAuth 2.0 with JWT.")


def test_verify_anchor_succeeds_when_quote_present(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "raw" / "local").mkdir(parents=True)
    source_file = workspace / "raw" / "local" / "source.md"
    source_file.write_text(
        "# Source\n\nThe auth layer uses OAuth 2.0 with JWT.\n",
        encoding="utf-8",
    )
    anchor = create_anchor(
        "raw/local/source.md",
        "The auth layer uses OAuth 2.0 with JWT.",
    )
    result = verify_quote_anchor(anchor, workspace)
    assert result.status == "verified"
    assert result.found_at_offset is not None


def test_verify_anchor_fails_when_quote_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "raw" / "local").mkdir(parents=True)
    source_file = workspace / "raw" / "local" / "source.md"
    source_file.write_text("# Source\n\nNo matching content here.\n", encoding="utf-8")

    anchor = create_anchor("raw/local/source.md", "this quote does not exist")
    result = verify_quote_anchor(anchor, workspace)
    assert result.status == "quote_not_found"


def test_verify_anchor_fails_when_source_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    anchor = create_anchor("raw/local/nonexistent.md", "some quote")
    result = verify_quote_anchor(anchor, workspace)
    assert result.status == "source_missing"


def test_verify_anchor_detects_source_drift(tmp_path: Path) -> None:
    """If the source file is edited after the anchor was created, the hash
    check should still pass as long as the quote text is unchanged."""
    workspace = tmp_path / "ws"
    (workspace / "raw" / "local").mkdir(parents=True)
    source_file = workspace / "raw" / "local" / "source.md"

    original = "# Source\n\nThe auth layer uses OAuth 2.0 with JWT.\n"
    source_file.write_text(original, encoding="utf-8")
    anchor = create_anchor("raw/local/source.md", "The auth layer uses OAuth 2.0 with JWT.", original)

    # Add content around the quote — the quote itself is unchanged
    modified = "# Source v2\n\nPrefix. The auth layer uses OAuth 2.0 with JWT. Suffix.\n"
    source_file.write_text(modified, encoding="utf-8")

    result = verify_quote_anchor(anchor, workspace)
    assert result.status == "verified"
