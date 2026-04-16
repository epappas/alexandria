"""Verifier protocol — the interface any verifier implementation must honor.

Per ``13_hostile_verifier.md``: one abstract method, one return type. The
deterministic verifier (Phase 2a, no LLM) and the hostile verifier (Phase 2b,
with LLM) both implement this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class ClaimFinding:
    """Result of checking one citation claim."""

    footnote_id: str
    source_file: str
    status: Literal[
        "verified",           # hash check passed
        "hash_mismatch",      # quote found but hash differs
        "quote_not_found",    # verbatim quote not in source
        "source_missing",     # source file doesn't exist
        "no_quote_provided",  # footnote has no verbatim quote
    ]
    message: str | None = None


@dataclass
class VerifierVerdict:
    """The verifier's decision about a staged write plan."""

    verdict: Literal["commit", "reject", "revise"]
    reasoning: str
    claim_findings: list[ClaimFinding] = field(default_factory=list)
    convergence_violations: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)


class Verifier(Protocol):
    """The verification contract from ``13_hostile_verifier.md``.

    Implementations:
    - ``DeterministicVerifier`` (Phase 2a): hash checks only, no LLM calls.
    - ``HostileVerifier`` (Phase 2b): deterministic + LLM semantic checks.
    """

    def verify(
        self,
        run_id: str,
        workspace_path: Path,
        staged_dir: Path,
    ) -> VerifierVerdict:
        """Verify a staged write plan. Returns commit, reject, or revise."""
        ...
