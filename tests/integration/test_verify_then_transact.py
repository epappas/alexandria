"""Integration test: verify-then-commit/reject pipeline.

The AI-engineer called this the MISSING integration test: the two core
Phase 2a subsystems (verifier + transaction) composed end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.core.runs import (
    RunStatus,
    commit_run,
    create_run,
    get_staged_dir,
    read_run_status,
    reject_run,
)
from alexandria.core.verifier import DeterministicVerifier


@pytest.fixture
def workspace_for_pipeline(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace with a raw source and a home directory for runs."""
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    (ws / "raw" / "local").mkdir(parents=True)
    (ws / "wiki").mkdir(parents=True)

    (ws / "raw" / "local" / "acme-api-v1.md").write_text(
        "# Acme API Spec v1\n\n"
        "The auth layer uses OAuth 2.0 with JWT.\n"
        "Token refresh is served at the path /oauth/refresh.\n",
        encoding="utf-8",
    )
    return home, ws


def test_valid_content_passes_verifier_and_commits(
    workspace_for_pipeline: tuple[Path, Path],
) -> None:
    """End-to-end: stage valid content → verifier passes → commit succeeds."""
    home, ws = workspace_for_pipeline

    run = create_run(home, "global", "test", "ingest")
    staged = get_staged_dir(home, run.run_id)
    (staged / "concepts").mkdir()
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Acme uses OAuth 2.0 with JWT.[^1]\n\n"
        '[^1]: acme-api-v1.md — "The auth layer uses OAuth 2.0 with JWT."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)

    assert verdict.verdict == "commit"

    committed = commit_run(home, run.run_id, ws)
    assert "concepts/auth.md" in committed
    assert (ws / "wiki" / "concepts" / "auth.md").exists()
    assert read_run_status(home, run.run_id) == RunStatus.COMMITTED


def test_fabricated_citation_fails_verifier_and_rejects(
    workspace_for_pipeline: tuple[Path, Path],
) -> None:
    """End-to-end: stage fabricated content → verifier rejects → wiki untouched."""
    home, ws = workspace_for_pipeline

    # Ensure wiki has existing content that must survive
    (ws / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
    (ws / "wiki" / "concepts" / "auth.md").write_text(
        "original content", encoding="utf-8"
    )

    run = create_run(home, "global", "test", "ingest")
    staged = get_staged_dir(home, run.run_id)
    (staged / "concepts").mkdir()
    (staged / "concepts" / "auth.md").write_text(
        "# Authentication\n\n"
        "Acme uses SAML for enterprise auth.[^1]\n\n"
        '[^1]: acme-api-v1.md — "Acme uses SAML for enterprise authentication."\n',
        encoding="utf-8",
    )

    verifier = DeterministicVerifier()
    verdict = verifier.verify("test-run", ws, staged)

    assert verdict.verdict == "reject"

    reject_run(home, run.run_id, verdict.reasoning)
    assert read_run_status(home, run.run_id) == RunStatus.REJECTED
    assert (ws / "wiki" / "concepts" / "auth.md").read_text(encoding="utf-8") == "original content"


def test_convergence_hedge_passes_verifier(
    workspace_for_pipeline: tuple[Path, Path],
) -> None:
    """A properly hedged disputed block with both claims passes."""
    home, ws = workspace_for_pipeline

    run = create_run(home, "global", "test", "ingest")
    staged = get_staged_dir(home, run.run_id)
    (staged / "concepts").mkdir()
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

    committed = commit_run(home, run.run_id, ws)
    assert "concepts/auth.md" in committed
    content = (ws / "wiki" / "concepts" / "auth.md").read_text(encoding="utf-8")
    assert "::: disputed" in content
    assert "Updated 2026-04-16 per RFC 0034" in content
