"""Fabrication corpus — runs the verifier_evasion fixtures through the
verifier and reports catch rate per tier.

Tier 1 cases are deterministic-catchable (quote_not_found, source_missing,
no_footnotes, convergence_violation). The deterministic verifier should
return ``reject`` for every tier-1 case.

Tier 2 cases pass the deterministic check (quote is verbatim) but the
claim does not actually follow from the quote. Catching these requires
the LLM-judged hostile verifier; tier-2 cases are reported separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from alexandria.core.verifier.deterministic import DeterministicVerifier
from alexandria.core.verifier.protocol import Verifier, VerifierVerdict

CORPUS_ROOT = Path(__file__).parent / "fabrication_fixtures"


@dataclass(frozen=True)
class FabricationCase:
    """One fabrication test case loaded from disk."""

    case_id: str
    tier: int
    fabrication_type: str
    expected_findings: list[str]
    expected_convergence_violation: bool
    expected_llm_caught: bool
    description: str
    staged_dir: Path


@dataclass(frozen=True)
class CaseResult:
    """Outcome of running one case through a verifier."""

    case: FabricationCase
    verdict: str
    caught: bool
    finding_statuses: list[str]
    convergence_violations: list[str]


@dataclass(frozen=True)
class CorpusResult:
    """Aggregate outcome for tier-1 + tier-2 over the whole corpus."""

    tier1_total: int
    tier1_caught: int
    tier2_total: int
    tier2_caught: int
    tier2_pending: int
    case_results: list[CaseResult]

    @property
    def tier1_catch_rate(self) -> float:
        return self.tier1_caught / self.tier1_total if self.tier1_total else 0.0

    @property
    def tier2_catch_rate(self) -> float:
        evaluated = self.tier2_total - self.tier2_pending
        return self.tier2_caught / evaluated if evaluated else 0.0


def load_cases(corpus_root: Path = CORPUS_ROOT) -> list[FabricationCase]:
    """Load every fabrication case from the corpus directory.

    Each case directory must contain ``meta.json`` plus a ``staged/`` subtree.
    """
    cases_dir = corpus_root / "cases"
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"corpus cases dir not found: {cases_dir}")

    cases: list[FabricationCase] = []
    for case_dir in sorted(cases_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        meta_path = case_dir / "meta.json"
        staged = case_dir / "staged"
        if not meta_path.is_file() or not staged.is_dir():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cases.append(FabricationCase(
            case_id=case_dir.name,
            tier=int(meta["tier"]),
            fabrication_type=str(meta["fabrication_type"]),
            expected_findings=list(meta.get("expected_findings", [])),
            expected_convergence_violation=bool(
                meta.get("expected_convergence_violation", False)
            ),
            expected_llm_caught=bool(meta.get("expected_llm_caught", False)),
            description=str(meta.get("description", "")),
            staged_dir=staged,
        ))
    return cases


def _was_caught_tier1(case: FabricationCase, verdict: VerifierVerdict) -> bool:
    if verdict.verdict != "reject":
        return False
    if case.expected_convergence_violation:
        return len(verdict.convergence_violations) > 0
    statuses = {f.status for f in verdict.claim_findings}
    return any(expected in statuses for expected in case.expected_findings)


def run_corpus(
    corpus_root: Path = CORPUS_ROOT,
    semantic_verifier: Verifier | None = None,
) -> CorpusResult:
    """Run every case through a verifier and report catch rates per tier.

    The deterministic verifier is always used for tier-1. If
    ``semantic_verifier`` is provided, tier-2 cases run through it; otherwise
    tier-2 cases are reported as ``pending`` (no LLM available).
    """
    cases = load_cases(corpus_root)
    workspace = corpus_root / "workspace"
    deterministic = DeterministicVerifier()

    tier1_total = tier1_caught = 0
    tier2_total = tier2_caught = tier2_pending = 0
    case_results: list[CaseResult] = []

    for case in cases:
        if case.tier == 1:
            verdict = deterministic.verify(case.case_id, workspace, case.staged_dir)
            caught = _was_caught_tier1(case, verdict)
            tier1_total += 1
            tier1_caught += int(caught)
            case_results.append(_to_result(case, verdict, caught))
            continue

        tier2_total += 1
        if semantic_verifier is None:
            verdict = deterministic.verify(case.case_id, workspace, case.staged_dir)
            tier2_pending += 1
            case_results.append(_to_result(case, verdict, caught=False))
            continue

        verdict = semantic_verifier.verify(
            case.case_id, workspace, case.staged_dir,
        )
        caught = verdict.verdict in ("reject", "revise")
        tier2_caught += int(caught)
        case_results.append(_to_result(case, verdict, caught))

    return CorpusResult(
        tier1_total=tier1_total,
        tier1_caught=tier1_caught,
        tier2_total=tier2_total,
        tier2_caught=tier2_caught,
        tier2_pending=tier2_pending,
        case_results=case_results,
    )


def _to_result(
    case: FabricationCase, verdict: VerifierVerdict, caught: bool,
) -> CaseResult:
    return CaseResult(
        case=case,
        verdict=verdict.verdict,
        caught=caught,
        finding_statuses=[f.status for f in verdict.claim_findings],
        convergence_violations=list(verdict.convergence_violations),
    )
