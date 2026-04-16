"""Tests for the deterministic verifier — the Phase 2a correctness gate.

These tests prove the verifier catches fabricated citations, missing sources,
and convergence policy violations WITHOUT any LLM calls. Pure hash checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.core.verifier import DeterministicVerifier, VerifierVerdict


@pytest.fixture
def workspace_for_verify(tmp_path: Path) -> Path:
    """A workspace with raw sources that citations should reference."""
    ws = tmp_path / "ws"
    (ws / "raw" / "local").mkdir(parents=True)
    (ws / "wiki" / "concepts").mkdir(parents=True)

    # A real raw source with known content
    (ws / "raw" / "local" / "acme-api-v1.md").write_text(
        "# Acme API Spec v1\n\n"
        "## Authentication\n"
        "The auth layer uses OAuth 2.0 with JWT.\n\n"
        "## Endpoints\n"
        "Token refresh is served at the path /oauth/refresh.\n",
        encoding="utf-8",
    )
    return ws


def test_verifier_commits_valid_citations(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A staged page with correct verbatim quotes from real sources passes."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Acme uses OAuth 2.0 with JWT.[^1]\n\n"
        '[^1]: acme-api-v1.md — "The auth layer uses OAuth 2.0 with JWT."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "commit"
    assert any(f.status == "verified" for f in verdict.claim_findings)


def test_verifier_rejects_fabricated_quote(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A citation with a quote that doesn't exist in the source is REJECTED.

    This is the single most important test in the entire project — it proves
    the deterministic citation check catches fabrication without any LLM call.
    """
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Acme uses SAML for enterprise auth.[^1]\n\n"
        '[^1]: acme-api-v1.md — "Acme uses SAML for enterprise authentication."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "reject"
    assert any(f.status == "quote_not_found" for f in verdict.claim_findings)


def test_verifier_rejects_missing_source(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A citation referencing a file that doesn't exist is REJECTED."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Some claim.[^1]\n\n"
        '[^1]: nonexistent-file.md — "This file does not exist."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "reject"
    assert any(f.status == "source_missing" for f in verdict.claim_findings)


def test_verifier_rejects_page_without_citations(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A non-structural wiki page with no footnotes is REJECTED."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Acme uses OAuth 2.0 with JWT.\n\n"
        "No citations here.\n",
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "reject"
    assert any("no footnotes" in (f.message or "") for f in verdict.claim_findings)


def test_verifier_allows_structural_pages_without_citations(
    workspace_for_verify: Path, tmp_path: Path
) -> None:
    """overview.md, index.md, and log.md are exempt from citation requirements."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "overview.md").write_text("# Overview\n\nSummary without citations.\n", encoding="utf-8")
    (staged / "index.md").write_text("# Index\n\n| Page | Summary |\n", encoding="utf-8")

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "commit"


def test_verifier_detects_bad_hedge_format(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A ::: disputed block without the required 'Updated YYYY-MM-DD per' is a violation."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "::: disputed\n"
        "Old claim.[^1]\n"
        "New claim without the required date marker.\n"
        ":::\n\n"
        '[^1]: acme-api-v1.md — "The auth layer uses OAuth 2.0 with JWT."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "reject"
    assert len(verdict.convergence_violations) > 0


def test_verifier_accepts_proper_hedge(workspace_for_verify: Path, tmp_path: Path) -> None:
    """A ::: disputed block WITH the required markers passes."""
    ws = workspace_for_verify
    staged = tmp_path / "staged"
    (staged / "concepts").mkdir(parents=True)
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "::: disputed\n"
        "The auth layer uses OAuth 2.0 with JWT.[^1]\n\n"
        "**Updated 2026-04-16 per RFC 0034:** The endpoint moved to /auth/v2/refresh.[^2]\n"
        ":::\n\n"
        '[^1]: acme-api-v1.md — "The auth layer uses OAuth 2.0 with JWT."\n'
        '[^2]: acme-api-v1.md — "Token refresh is served at the path /oauth/refresh."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)
    assert verdict.verdict == "commit"
