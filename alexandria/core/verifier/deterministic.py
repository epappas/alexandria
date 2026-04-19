"""Deterministic verifier — Phase 2a, no LLM calls.

Runs the hash-based checks from ``13_hostile_verifier.md`` check #3:
1. Every staged wiki page must have at least one footnote (structural pages exempt).
2. Every footnote with a verbatim quote must pass the sha256 hash check against
   the live raw source.
3. Source files referenced by footnotes must exist on disk.

A hash mismatch or missing source is a **reject**. A missing quote (footnote
without verbatim quote) is flagged but not a reject in Phase 2a — the semantic
check in Phase 2b will handle those.
"""

from __future__ import annotations

from pathlib import Path

from alexandria.core.citations import (
    QuoteAnchor,
    extract_footnotes,
    verify_quote_anchor,
)
from alexandria.core.verifier.protocol import (
    ClaimFinding,
    VerifierVerdict,
)

STRUCTURAL_PAGES = {"overview.md", "index.md", "log.md"}


class DeterministicVerifier:
    """Verifier that uses only deterministic hash checks — no LLM calls.

    This is the Phase 2a verifier. It catches:
    - Fabricated citations (wrong filename, wrong page, invented quote)
    - Source drift (quote exists but source was edited → hash mismatch)
    - Missing sources (file deleted or not yet ingested)

    It does NOT catch:
    - Semantically misleading quotes (quote is real but doesn't support the claim)
    - Cherry-picked quotes (technically present, contextually wrong)

    Those require the hostile LLM verifier in Phase 2b.
    """

    def verify(
        self,
        run_id: str,
        workspace_path: Path,
        staged_dir: Path,
    ) -> VerifierVerdict:
        all_findings: list[ClaimFinding] = []
        convergence_violations: list[str] = []
        has_reject = False

        # Check every staged markdown file
        for staged_file in sorted(staged_dir.rglob("*.md")):
            if not staged_file.is_file():
                continue

            rel = staged_file.relative_to(staged_dir)
            is_structural = rel.name in STRUCTURAL_PAGES

            text = staged_file.read_text(encoding="utf-8")
            footnotes = extract_footnotes(text)

            # Citation requirement: non-structural pages need footnotes
            if not is_structural and not footnotes:
                all_findings.append(
                    ClaimFinding(
                        footnote_id="*",
                        source_file="*",
                        status="no_quote_provided",
                        message=f"{rel}: no footnotes found (non-structural page requires citations)",
                    )
                )
                has_reject = True
                continue

            # Check each footnote
            for fn in footnotes:
                if not fn.has_quote:
                    all_findings.append(
                        ClaimFinding(
                            footnote_id=fn.footnote_id,
                            source_file=fn.source_file,
                            status="no_quote_provided",
                            message=f"[^{fn.footnote_id}]: {fn.source_file} — no verbatim quote",
                        )
                    )
                    continue

                # Build anchor and verify
                anchor = QuoteAnchor(
                    source_file=fn.source_file,
                    quote=fn.quote or "",
                    quote_hash="",  # computed by verify
                    offset=None,
                )
                # Re-create with proper hash
                from alexandria.core.citations.anchors import create_anchor

                anchor = create_anchor(
                    source_file=fn.source_file,
                    quote=fn.quote or "",
                )
                result = verify_quote_anchor(anchor, workspace_path)

                finding = ClaimFinding(
                    footnote_id=fn.footnote_id,
                    source_file=fn.source_file,
                    status=result.status,
                    message=result.message,
                )
                all_findings.append(finding)

                if result.status in ("hash_mismatch", "source_missing", "quote_not_found"):
                    has_reject = True

            # Convergence policy check: if the page has ::: disputed markers,
            # verify they have the required "Updated YYYY-MM-DD per" format
            if "::: disputed" in text:
                if "Updated " not in text or " per " not in text:
                    convergence_violations.append(
                        f"{rel}: has ::: disputed block but missing 'Updated YYYY-MM-DD per <source>' marker"
                    )

        if has_reject:
            reject_findings = [f for f in all_findings if f.status not in ("verified", "no_quote_provided")]
            reasons = [f"[^{f.footnote_id}] {f.source_file}: {f.status}" for f in reject_findings]
            return VerifierVerdict(
                verdict="reject",
                reasoning="Deterministic citation check failed: " + "; ".join(reasons),
                claim_findings=all_findings,
                convergence_violations=convergence_violations,
            )

        if convergence_violations:
            return VerifierVerdict(
                verdict="reject",
                reasoning="Convergence policy violation: " + "; ".join(convergence_violations),
                claim_findings=all_findings,
                convergence_violations=convergence_violations,
            )

        return VerifierVerdict(
            verdict="commit",
            reasoning="All deterministic checks passed",
            claim_findings=all_findings,
            convergence_violations=[],
        )
