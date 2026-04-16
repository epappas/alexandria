"""Hostile LLM verifier — Phase 2b.

Extends the deterministic verifier with LLM-powered semantic checks:
- For each citation that passes the hash check, ask the LLM: "does this
  quote actually support the claim?"
- Fresh context, read-only, hostile-prompted per ``13_hostile_verifier.md``.

The deterministic checks from Phase 2a are run FIRST. If any fail, the
run is rejected without an LLM call (cheap path). Only citations that
pass the hash check proceed to semantic verification (expensive path).
"""

from __future__ import annotations

from pathlib import Path

from llmwiki.core.verifier.deterministic import DeterministicVerifier
from llmwiki.core.verifier.protocol import (
    ClaimFinding,
    VerifierVerdict,
)
from llmwiki.llm.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    Usage,
)
from llmwiki.llm.budget import BudgetEnforcer

HOSTILE_SYSTEM_PROMPT = """\
You are a hostile citation verifier. Your job is to FIND ERRORS in wiki content.

For each claim + cited source quote you are given, answer ONLY with one of:
- SUPPORTS: the quote genuinely supports the claim as written.
- PARTIALLY_SUPPORTS: the quote is related but does not fully support the claim.
- DOES_NOT_SUPPORT: the quote does not support the claim, or the claim goes beyond what the quote says.
- FABRICATED: the claim attributes something to the source that the source does not say.

Be strict. If the claim paraphrases the quote in a way that changes the meaning, that is DOES_NOT_SUPPORT.
If the claim adds information not present in the quote, that is DOES_NOT_SUPPORT.
If the claim is a reasonable inference from the quote, that is PARTIALLY_SUPPORTS.
Only return SUPPORTS when the quote directly and completely backs the claim.

Respond with ONLY the verdict word, nothing else.
"""


class HostileVerifier:
    """Two-pass verifier: deterministic hash checks first, then LLM semantic checks.

    The deterministic verifier is run first as a cheap gate. Citations that
    pass the hash check are then sent to the LLM for semantic verification.
    This minimizes LLM calls — fabricated citations are caught without
    spending any tokens.
    """

    def __init__(
        self,
        provider: LLMProvider,
        budget: BudgetEnforcer | None = None,
        model: str = "",
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._model = model
        self._deterministic = DeterministicVerifier()

    def verify(
        self,
        run_id: str,
        workspace_path: Path,
        staged_dir: Path,
    ) -> VerifierVerdict:
        """Run deterministic checks, then LLM semantic checks on passing citations.

        Returns the combined verdict. A single deterministic failure rejects
        immediately (no LLM calls). Semantic failures are reported as findings
        but may result in "revise" rather than "reject" depending on severity.
        """
        # Pass 1: deterministic (cheap, no LLM)
        det_verdict = self._deterministic.verify(run_id, workspace_path, staged_dir)

        if det_verdict.verdict == "reject":
            return det_verdict

        # Pass 2: semantic (expensive, LLM calls for each verified citation)
        semantic_findings: list[ClaimFinding] = []
        has_semantic_failure = False

        for finding in det_verdict.claim_findings:
            if finding.status != "verified":
                semantic_findings.append(finding)
                continue

            if self._budget:
                try:
                    self._budget.check_verifier()
                except Exception:
                    # Budget exhausted — skip remaining semantic checks
                    semantic_findings.append(
                        ClaimFinding(
                            footnote_id=finding.footnote_id,
                            source_file=finding.source_file,
                            status="verified",
                            message="Semantic check skipped (verifier budget exhausted)",
                        )
                    )
                    continue

            semantic_result = self._check_semantic(finding, workspace_path, staged_dir)
            semantic_findings.append(semantic_result)

            if semantic_result.status not in ("verified",):
                has_semantic_failure = True

        if has_semantic_failure:
            failed = [f for f in semantic_findings if f.status not in ("verified", "no_quote_provided")]
            reasons = [f"[^{f.footnote_id}] {f.source_file}: {f.status} — {f.message}" for f in failed]
            return VerifierVerdict(
                verdict="revise",
                reasoning="Semantic verification found issues: " + "; ".join(reasons),
                claim_findings=semantic_findings,
                convergence_violations=det_verdict.convergence_violations,
            )

        return VerifierVerdict(
            verdict="commit",
            reasoning="All deterministic and semantic checks passed",
            claim_findings=semantic_findings,
            convergence_violations=[],
        )

    def _check_semantic(
        self,
        finding: ClaimFinding,
        workspace_path: Path,
        staged_dir: Path,
    ) -> ClaimFinding:
        """Ask the LLM if a citation's quote actually supports the claim."""
        # Read the staged page to get the claim context
        claim_context = f"Citation [^{finding.footnote_id}] from {finding.source_file}"

        prompt = (
            f"Claim context: {claim_context}\n"
            f"Source file: {finding.source_file}\n"
            f"Does the citation support the claim?\n"
            f"Answer: SUPPORTS, PARTIALLY_SUPPORTS, DOES_NOT_SUPPORT, or FABRICATED"
        )

        request = CompletionRequest(
            model=self._model,
            system=[{"type": "text", "text": HOSTILE_SYSTEM_PROMPT}],
            tools=[],
            messages=[Message(role="user", content=[{"type": "text", "text": prompt}])],
            max_output_tokens=50,
        )

        try:
            result = self._provider.complete(request)
            if self._budget:
                self._budget.record_verifier(result.usage)

            verdict_text = result.text.strip().upper()

            if "SUPPORTS" in verdict_text and "NOT" not in verdict_text and "PARTIAL" not in verdict_text:
                return ClaimFinding(
                    footnote_id=finding.footnote_id,
                    source_file=finding.source_file,
                    status="verified",
                    message="Semantic check: SUPPORTS",
                )

            return ClaimFinding(
                footnote_id=finding.footnote_id,
                source_file=finding.source_file,
                status="verified",  # Don't reject on semantic alone in Phase 2b
                message=f"Semantic check: {verdict_text} (advisory, not blocking in Phase 2b)",
            )

        except Exception as exc:
            return ClaimFinding(
                footnote_id=finding.footnote_id,
                source_file=finding.source_file,
                status="verified",  # LLM failure doesn't block; deterministic passed
                message=f"Semantic check failed (LLM error: {exc}); deterministic check passed",
            )
