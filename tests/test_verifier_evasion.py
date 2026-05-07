"""Tests for the verifier_evasion fabrication corpus.

Enforces the Phase 2a acceptance criterion from
``docs/PLAN_AMENDMENTS.md`` (B5/I2):

- ≥90% catch rate on tier-1 deterministic fabrications
- ≥70% on tier-2 LLM-judged fabrications (skipped here — no LLM provider
  in the unit-test environment; covered by ``M3FabricationCatch`` once a
  semantic verifier is wired)

Each tier-1 case must produce ``reject`` with the expected finding type.
Tier-2 cases must pass deterministic checks (their staged citation is
verbatim) so the deterministic verifier returns ``commit``; the semantic
failure can only be caught by the hostile verifier.
"""

from __future__ import annotations

from alexandria.eval.fabrication_corpus import (
    CORPUS_ROOT,
    load_cases,
    run_corpus,
)


def test_corpus_has_minimum_case_counts() -> None:
    """Phase 2a calls for 20-30 cases. Floor: 12 tier-1 + 12 tier-2."""
    cases = load_cases()
    tier1 = [c for c in cases if c.tier == 1]
    tier2 = [c for c in cases if c.tier == 2]
    assert len(tier1) >= 12, f"need ≥12 tier-1 cases, got {len(tier1)}"
    assert len(tier2) >= 12, f"need ≥12 tier-2 cases, got {len(tier2)}"


def test_every_case_has_required_files() -> None:
    """Each case dir must have meta.json and a non-empty staged/ subtree."""
    for case in load_cases():
        assert case.staged_dir.is_dir(), f"{case.case_id}: staged dir missing"
        staged_pages = list(case.staged_dir.rglob("*.md"))
        assert staged_pages, f"{case.case_id}: no staged markdown pages"


def test_workspace_sources_exist() -> None:
    """The shared corpus workspace must have the source files cited by cases."""
    raw_dir = CORPUS_ROOT / "workspace" / "raw" / "local"
    assert raw_dir.is_dir(), "corpus workspace raw/local missing"
    sources = list(raw_dir.glob("*.md"))
    assert len(sources) >= 3, f"need ≥3 source files, got {len(sources)}"


def test_tier1_catch_rate_meets_phase_2a_threshold() -> None:
    """The deterministic verifier must catch ≥90% of tier-1 fabrications."""
    result = run_corpus()
    assert result.tier1_total >= 12
    missed = [cr.case.case_id for cr in result.case_results
              if cr.case.tier == 1 and not cr.caught]
    assert result.tier1_catch_rate >= 0.90, (
        f"tier-1 catch rate {result.tier1_catch_rate:.2%} below 0.90 "
        f"threshold (missed: {missed})"
    )


def test_tier2_passes_deterministic_check() -> None:
    """Tier-2 fabrications are verbatim-correct; deterministic should not catch them."""
    result = run_corpus()
    tier2_results = [cr for cr in result.case_results if cr.case.tier == 2]
    assert tier2_results, "no tier-2 cases ran"
    for cr in tier2_results:
        assert cr.verdict == "commit", (
            f"tier-2 case {cr.case.case_id} unexpectedly failed deterministic "
            f"check (verdict={cr.verdict}, statuses={cr.finding_statuses}); "
            f"the citation should be verbatim and the failure semantic"
        )


def test_tier1_findings_match_meta() -> None:
    """Each tier-1 catch must produce the finding type its meta.json declares."""
    result = run_corpus()
    for cr in result.case_results:
        if cr.case.tier != 1 or not cr.caught:
            continue
        if cr.case.expected_convergence_violation:
            assert cr.convergence_violations, (
                f"{cr.case.case_id}: expected a convergence violation, got none"
            )
            continue
        statuses = set(cr.finding_statuses)
        for expected in cr.case.expected_findings:
            assert expected in statuses, (
                f"{cr.case.case_id}: expected finding {expected!r}, "
                f"got statuses {statuses}"
            )
