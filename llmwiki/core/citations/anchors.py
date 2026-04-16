"""Verbatim quote anchors — deterministic hash-based citation verification.

Per ``13_hostile_verifier.md``, every citation must include a verbatim quote
from the raw source. The quote's sha256 hash is stored in
``wiki_claim_provenance.source_quote_hash``. Verification re-computes the
hash against the live raw file — **no LLM judgment needed** for this check.

Anchor format is versioned (``anchor_format_version``) from day one per the
llm-architect's recommendation. Version 1 uses plain sha256 over the exact
UTF-8 bytes of the quote string with leading/trailing whitespace stripped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ANCHOR_FORMAT_VERSION = 1


@dataclass(frozen=True)
class QuoteAnchor:
    """A verbatim quote from a raw source, with its hash for verification."""

    source_file: str
    quote: str
    quote_hash: str
    offset: int | None  # char offset in the source file (best-effort)
    anchor_format_version: int = ANCHOR_FORMAT_VERSION


@dataclass(frozen=True)
class AnchorVerifyResult:
    """Result of verifying a quote anchor against the live raw file."""

    status: Literal["verified", "hash_mismatch", "quote_not_found", "source_missing"]
    source_file: str
    expected_hash: str
    actual_hash: str | None = None
    found_at_offset: int | None = None
    message: str | None = None


def compute_quote_hash(quote: str) -> str:
    """Compute the sha256 of a quote's stripped UTF-8 bytes.

    This is anchor_format_version=1. Future versions may normalize
    unicode (NFC), collapse whitespace, etc.
    """
    return hashlib.sha256(quote.strip().encode("utf-8")).hexdigest()


def create_anchor(
    source_file: str,
    quote: str,
    source_text: str | None = None,
) -> QuoteAnchor:
    """Create a quote anchor from a source file and a verbatim quote.

    If ``source_text`` is provided, the offset is computed by finding the
    quote in the source text. If not found, offset is None.
    """
    quote_stripped = quote.strip()
    quote_hash = compute_quote_hash(quote_stripped)
    offset: int | None = None
    if source_text is not None:
        idx = source_text.find(quote_stripped)
        if idx >= 0:
            offset = idx
    return QuoteAnchor(
        source_file=source_file,
        quote=quote_stripped,
        quote_hash=quote_hash,
        offset=offset,
    )


def verify_quote_anchor(
    anchor: QuoteAnchor,
    workspace_path: Path,
) -> AnchorVerifyResult:
    """Verify a quote anchor against the live raw file on disk.

    This is the **deterministic** citation check from ``13_hostile_verifier.md``
    check #3. No LLM judgment — pure hash comparison.

    Returns:
        AnchorVerifyResult with status:
        - ``verified``: hash matches at the recorded offset (or found elsewhere)
        - ``hash_mismatch``: quote found but hash differs (source was edited)
        - ``quote_not_found``: the quote text is not in the source file
        - ``source_missing``: the source file does not exist
    """
    # Resolve the source file (search raw/ if relative path)
    source_path = _resolve_source_path(workspace_path, anchor.source_file)
    if source_path is None:
        return AnchorVerifyResult(
            status="source_missing",
            source_file=anchor.source_file,
            expected_hash=anchor.quote_hash,
            message=f"Source file not found: {anchor.source_file}",
        )

    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return AnchorVerifyResult(
            status="source_missing",
            source_file=anchor.source_file,
            expected_hash=anchor.quote_hash,
            message=f"Error reading source: {exc}",
        )

    # Try to find the quote in the source text
    idx = source_text.find(anchor.quote)
    if idx < 0:
        return AnchorVerifyResult(
            status="quote_not_found",
            source_file=anchor.source_file,
            expected_hash=anchor.quote_hash,
            message="Verbatim quote not found in source file",
        )

    # Found the quote — verify the hash
    actual_hash = compute_quote_hash(source_text[idx : idx + len(anchor.quote)])
    if actual_hash == anchor.quote_hash:
        return AnchorVerifyResult(
            status="verified",
            source_file=anchor.source_file,
            expected_hash=anchor.quote_hash,
            actual_hash=actual_hash,
            found_at_offset=idx,
        )

    return AnchorVerifyResult(
        status="hash_mismatch",
        source_file=anchor.source_file,
        expected_hash=anchor.quote_hash,
        actual_hash=actual_hash,
        found_at_offset=idx,
        message="Quote found but hash differs — source may have been edited",
    )


def _resolve_source_path(workspace_path: Path, source_ref: str) -> Path | None:
    """Resolve a source file reference to an absolute path."""
    # Try as-is relative to workspace
    candidate = workspace_path / source_ref.lstrip("/")
    if candidate.exists() and candidate.is_file():
        return candidate

    # Try under raw/
    raw_dir = workspace_path / "raw"
    if raw_dir.exists():
        name = Path(source_ref).name
        for match in raw_dir.rglob(name):
            if match.is_file():
                return match

    return None
