"""``alexandria ingest`` — the core ingest pipeline.

Reads a raw source, stages wiki writes via cascade operations, runs the
verifier, and commits or rejects. This is the complete write path from
``04_guardian_agent.md``.

Phase 2b ships the basic ingest for local markdown files. Source adapters
(GitHub, RSS, etc.) arrive in Phase 4+.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alexandria.core.cascade import stage_cross_ref, stage_hedge, stage_merge, stage_new_page
from alexandria.core.citations import extract_footnotes
from alexandria.core.runs import (
    commit_run,
    create_run,
    get_staged_dir,
    reject_run,
)
from alexandria.core.verifier import DeterministicVerifier
from alexandria.db.connection import connect, db_path


class IngestError(Exception):
    """Raised on ingest failures."""


class IngestResult:
    """Result of an ingest operation."""

    def __init__(
        self,
        run_id: str,
        committed: bool,
        committed_paths: list[str],
        verdict_reasoning: str,
        source_path: str,
    ) -> None:
        self.run_id = run_id
        self.committed = committed
        self.committed_paths = committed_paths
        self.verdict_reasoning = verdict_reasoning
        self.source_path = source_path


@dataclass
class DedupResult:
    """Result of dedup check — unchanged, changed (with diff), or new."""

    status: str  # "unchanged" | "changed" | "new"
    added: int = 0
    removed: int = 0
    diff_preview: str = ""


def check_dedup(
    conn: sqlite3.Connection,
    workspace: str,
    content_hash: str,
    new_content: str,
    source_path: str = "",
) -> DedupResult:
    """Check if a document was already ingested. Returns diff info if changed."""
    # Exact hash match — unchanged
    if conn.execute(
        "SELECT 1 FROM documents WHERE workspace = ? AND content_hash = ? LIMIT 1",
        (workspace, content_hash),
    ).fetchone():
        return DedupResult(status="unchanged")

    # Path match with different hash — content changed
    if source_path:
        row = conn.execute(
            "SELECT content FROM documents WHERE workspace = ? AND path = ? LIMIT 1",
            (workspace, source_path),
        ).fetchone()
        if row:
            old_content = row["content"] or ""
            return _compute_diff(old_content, new_content)

    return DedupResult(status="new")


def _compute_diff(old: str, new: str) -> DedupResult:
    """Compute a diff summary between old and new content."""
    import difflib
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, n=1))

    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))

    if added == 0 and removed == 0:
        return DedupResult(status="unchanged")

    preview_lines = [d.rstrip() for d in diff[:10] if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))]
    return DedupResult(
        status="changed", added=added, removed=removed,
        diff_preview="\n".join(preview_lines[:5]),
    )


def ingest_file(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    source_file: Path,
    *,
    topic: str | None = None,
    verifier: DeterministicVerifier | None = None,
) -> IngestResult:
    """Ingest a single raw source file into the wiki.

    Steps:
    1. Read the source file.
    2. Copy it to raw/ if not already there.
    3. Stage a new wiki page with citations.
    4. Run the verifier.
    5. Commit or reject based on the verdict.

    This is the Phase 2b basic ingest — the guardian agent's cascade
    planning (which decides merge vs hedge vs new_page) is simplified
    to always create a new page. Full cascade intelligence arrives when
    the guardian agent loop is wired in Phase 2b/3.
    """
    if not source_file.exists():
        raise IngestError(f"Source file not found: {source_file}")

    # PDF extraction
    if source_file.suffix.lower() == ".pdf":
        source_content = _extract_pdf_content(source_file)
    else:
        source_content = source_file.read_text(encoding="utf-8")

    if not source_content.strip():
        raise IngestError(f"Source file is empty: {source_file}")

    # Dedup: check if content changed since last ingest
    content_hash = hashlib.sha256(source_content.encode()).hexdigest()
    raw_rel = ""
    if source_file.resolve().is_relative_to((workspace_path / "raw").resolve()):
        raw_rel = str(source_file.relative_to(workspace_path))
    dedup = DedupResult(status="new")
    if db_path(home).exists():
        with connect(db_path(home)) as conn:
            dedup = check_dedup(conn, workspace_slug, content_hash, source_content, raw_rel)
            if dedup.status == "unchanged":
                return IngestResult(
                    run_id="",
                    committed=False,
                    committed_paths=[],
                    verdict_reasoning="content unchanged (hash match)",
                    source_path=str(source_file),
                )

    # Ensure the source is in raw/ (skip if already there, e.g. from fetch_and_save)
    raw_dir = workspace_path / "raw"
    if source_file.resolve().is_relative_to(raw_dir.resolve()):
        raw_dest = source_file
    else:
        raw_dest = _ensure_in_raw(workspace_path, source_file, source_content)

    # Create a run
    run = create_run(home, workspace_slug, "cli:ingest", "ingest")

    # Record the run in SQLite
    if db_path(home).exists():
        with connect(db_path(home)) as conn:
            from alexandria.core.runs import insert_run_row
            conn.execute("BEGIN IMMEDIATE")
            try:
                insert_run_row(conn, run)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # Determine topic from the source path or use default
    resolved_topic = topic or _infer_topic(source_file)

    # Stage a new wiki page
    staged = get_staged_dir(home, run.run_id)
    slug = source_file.stem.lower().replace(" ", "-")
    cite_path = str(raw_dest.relative_to(workspace_path))

    # AST extraction for code files (deterministic, no LLM needed)
    from alexandria.core.code import detect_language, extract_structure
    lang = detect_language(source_file.suffix)
    code_structure = extract_structure(source_content, lang) if lang else None

    # Try LLM-powered processing first; fall back to extraction if unavailable
    from alexandria.core.llm_ingest import llm_process_content
    llm_result = llm_process_content(source_content, source_file.name, cite_path)

    if llm_result:
        title = llm_result["title"]
        body = llm_result["body"]
        if code_structure:
            body += "\n\n## Code Structure\n\n" + code_structure.to_markdown()
        footnote_lines = ""  # already embedded in body by the LLM
        llm_beliefs = llm_result.get("beliefs", [])
    elif code_structure:
        # Code file without LLM — use AST structure as the wiki page
        title = f"{source_file.name} ({code_structure.language})"
        body = code_structure.to_markdown()
        # Use module docstring or filename as citation quote
        quote = (code_structure.module_docstring.split("\n")[0][:80]
                 if code_structure.module_docstring else source_file.name)
        footnote_lines = f'[^1]: {cite_path} — "{quote}"'
        body += " [^1]"
        llm_beliefs = []
    else:
        # No LLM, no code structure — extract mechanically
        title = _extract_title_from_content(source_content) or \
                source_file.stem.replace("-", " ").replace("_", " ").title()

        footnotes = extract_footnotes(source_content)
        footnote_lines = "\n".join(fn.raw_line for fn in footnotes) if footnotes else ""

        body = _extract_body(source_content)

        if not footnote_lines:
            quote = _extract_representative_quote(source_content)
            if quote:
                footnote_lines = f'[^1]: {cite_path} — "{quote}"'
                body += " [^1]"

        llm_beliefs = []

    # Add AST-derived beliefs (deterministic, always available for code)
    if code_structure:
        ast_beliefs = code_structure.to_beliefs(resolved_topic, "")
        llm_beliefs.extend(ast_beliefs)

    raw_rel = raw_dest.relative_to(workspace_path)
    sources_line = f"{title}, {datetime.now(UTC).strftime('%Y-%m-%d')}"
    raw_line = f"[{source_file.name}](../../{raw_rel})"
    cite_path = str(raw_dest.relative_to(workspace_path))

    _execute_cascade(
        home, workspace_slug, workspace_path, staged,
        topic=resolved_topic, slug=slug, title=title, body=body,
        sources_line=sources_line, raw_line=raw_line,
        footnotes=footnote_lines, beliefs=llm_beliefs,
        cite_path=cite_path,
    )

    # Run the verifier
    if verifier is None:
        verifier = DeterministicVerifier()

    verdict = verifier.verify(run.run_id, workspace_path, staged)

    if verdict.verdict in ("commit",):
        committed_paths = commit_run(home, run.run_id, workspace_path)

        # Update run row + insert committed documents into SQLite
        if db_path(home).exists():
            with connect(db_path(home)) as conn:
                from alexandria.core.runs import update_run_row
                conn.execute("BEGIN IMMEDIATE")
                try:
                    update_run_row(
                        conn, run.run_id,
                        status="committed",
                        verdict="commit",
                        ended_at=datetime.now(UTC).isoformat(),
                    )

                    # Determine source provenance
                    from alexandria.core.source_kind import infer_source_kind, is_ai_authored
                    src_kind = infer_source_kind(source_file, str(raw_dest.relative_to(workspace_path)))
                    ai_flag = 1 if is_ai_authored(source_file, str(raw_dest.relative_to(workspace_path))) else 0

                    # Register committed wiki pages in documents table (populates FTS)
                    for rel_path in committed_paths:
                        wiki_file = workspace_path / "wiki" / rel_path
                        if wiki_file.exists():
                            wiki_content = wiki_file.read_text(encoding="utf-8")
                            wiki_hash = hashlib.sha256(wiki_content.encode()).hexdigest()
                            doc_id = f"doc-{hashlib.sha256(rel_path.encode()).hexdigest()[:12]}"
                            conn.execute(
                                """INSERT OR REPLACE INTO documents
                                  (id, workspace, layer, path, filename, file_type, content,
                                   content_hash, size_bytes, title, ai_authored,
                                   created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                        datetime('now'), datetime('now'))""",
                                (
                                    doc_id, workspace_slug, "wiki",
                                    f"wiki/{rel_path}", Path(rel_path).name, "md",
                                    wiki_content, wiki_hash, len(wiki_content), title,
                                    ai_flag,
                                ),
                            )

                    # Also register the raw source
                    raw_rel = raw_dest.relative_to(workspace_path)
                    raw_doc_id = f"doc-{hashlib.sha256(str(raw_rel).encode()).hexdigest()[:12]}"
                    conn.execute(
                        """INSERT OR REPLACE INTO documents
                          (id, workspace, layer, path, filename, file_type, content,
                           content_hash, size_bytes, title, ai_authored,
                           created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                datetime('now'), datetime('now'))""",
                        (
                            raw_doc_id, workspace_slug, "raw",
                            str(raw_rel), raw_dest.name,
                            source_file.suffix.lstrip(".") or "md",
                            source_content, hashlib.sha256(source_content.encode()).hexdigest(),
                            len(source_content), title, ai_flag,
                        ),
                    )

                    # Insert LLM-extracted beliefs with dedup
                    if llm_beliefs:
                        from alexandria.core.beliefs.model import Belief
                        from alexandria.core.beliefs.repository import (
                            find_duplicate_belief,
                            insert_belief,
                            supersede_beliefs_for_document,
                        )
                        wiki_rel = f"wiki/{committed_paths[0]}" if committed_paths else ""

                        # Supersede all existing beliefs for this doc first
                        supersede_beliefs_for_document(conn, wiki_rel, run.run_id)

                        for b in llm_beliefs:
                            stmt = b.get("statement", "")[:500]
                            subj = b.get("subject")
                            pred = b.get("predicate")
                            obj = b.get("object")

                            # Check if identical belief exists (was just superseded)
                            dup_id = find_duplicate_belief(
                                conn, workspace_slug, stmt, wiki_rel,
                                subj, pred, obj,
                            )
                            if dup_id:
                                # Restore the identical belief and refresh source_kind
                                # in case the AST path produces a more precise value.
                                restored_kind = b.get("source_kind") or src_kind
                                conn.execute(
                                    """UPDATE wiki_beliefs SET superseded_at = NULL,
                                       superseded_by_belief_id = NULL,
                                       superseded_in_run = NULL,
                                       supersession_reason = NULL,
                                       source_kind = ?
                                    WHERE belief_id = ?""",
                                    (restored_kind, dup_id),
                                )
                                continue

                            belief = Belief(
                                workspace=workspace_slug,
                                statement=stmt,
                                topic=b.get("topic", resolved_topic),
                                wiki_document_path=wiki_rel,
                                footnote_ids=b.get("footnote_ids", []),
                                subject=subj,
                                predicate=pred,
                                object=obj,
                                asserted_in_run=run.run_id,
                            )
                            insert_belief(conn, belief)
                            # Tag with source provenance. AST-extracted beliefs carry
                            # their own source_kind='code' and override the file kind.
                            belief_kind = b.get("source_kind") or src_kind
                            conn.execute(
                                "UPDATE wiki_beliefs SET source_kind = ? WHERE belief_id = ?",
                                (belief_kind, belief.belief_id),
                            )

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

        # Post-commit: discover cross-references (best-effort)
        if db_path(home).exists() and committed_paths:
            try:
                from alexandria.core.cascade.crossref import discover_cross_refs
                with connect(db_path(home)) as conn:
                    xrefs = discover_cross_refs(
                        conn, workspace_slug, workspace_path, committed_paths,
                    )
                    for xref in xrefs:
                        try:
                            xref_staged = get_staged_dir(home, f"{run.run_id}-xref")
                            stage_cross_ref(
                                xref_staged, workspace_path,
                                xref.from_page, xref.to_page, xref.label,
                            )
                            commit_run(home, f"{run.run_id}-xref", workspace_path)
                        except Exception:
                            continue
            except Exception:
                pass  # cross-refs are best-effort

        # Append to operation log
        from alexandria.core.wiki_log import append_log_entry
        pages = ", ".join(committed_paths[:3])
        append_log_entry(
            workspace_path, "ingest", f"Committed {title} -> {pages}",
            run_id=run.run_id,
        )

        return IngestResult(
            run_id=run.run_id,
            committed=True,
            committed_paths=committed_paths,
            verdict_reasoning=verdict.reasoning,
            source_path=str(source_file),
        )

    # Reject
    reject_run(home, run.run_id, verdict.reasoning)

    if db_path(home).exists():
        with connect(db_path(home)) as conn:
            from alexandria.core.runs import update_run_row
            conn.execute("BEGIN IMMEDIATE")
            try:
                update_run_row(
                    conn, run.run_id,
                    status="rejected",
                    verdict="reject",
                    reject_reason=verdict.reasoning,
                    ended_at=datetime.now(UTC).isoformat(),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    return IngestResult(
        run_id=run.run_id,
        committed=False,
        committed_paths=[],
        verdict_reasoning=verdict.reasoning,
        source_path=str(source_file),
    )


def _execute_cascade(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    staged: Path,
    *,
    topic: str,
    slug: str,
    title: str,
    body: str,
    sources_line: str,
    raw_line: str,
    footnotes: str,
    beliefs: list[dict],
    cite_path: str,
) -> Path:
    """Decide merge/hedge/new_page and execute the cascade operation."""
    from alexandria.core.cascade.decision import plan_cascade

    # Try cascade planning if DB exists
    own_wiki_path = f"wiki/{topic}/{slug}.md"
    if db_path(home).exists():
        try:
            with connect(db_path(home)) as conn:
                plan = plan_cascade(
                    conn, workspace_slug, workspace_path, title, body, beliefs,
                    exclude_path=own_wiki_path,
                )
        except Exception:
            plan = None
    else:
        plan = None

    if plan and plan.action == "merge" and plan.target_page:
        rel = plan.target_page.removeprefix("wiki/")
        return stage_merge(
            staged, workspace_path, rel,
            plan.section_heading, body,
            f'[^src]: {cite_path}' if cite_path else "",
        )

    if plan and plan.action == "hedge" and plan.target_page:
        return _execute_hedge(staged, workspace_path, plan, body, cite_path)

    # Default: new page (also handles cross_refs after commit in ingest_file)
    path = stage_new_page(
        staged, topic=topic, slug=slug, title=title, body=body,
        sources_line=sources_line, raw_line=raw_line, footnotes=footnotes,
    )

    # Stage cross-refs if any
    if plan and plan.cross_refs:
        for ref_path in plan.cross_refs:
            try:
                ref_rel = ref_path.removeprefix("wiki/")
                stage_cross_ref(staged, workspace_path, f"{topic}/{slug}.md", ref_rel)
            except Exception:
                continue
    return path


def _execute_hedge(
    staged: Path, workspace_path: Path, plan: CascadePlan,  # noqa: F821
    body: str, cite_path: str,
) -> Path:
    """Execute a hedge (contradiction) cascade operation."""
    rel = plan.target_page.removeprefix("wiki/")
    target = workspace_path / "wiki" / rel
    if not target.exists():
        raise IngestError(f"hedge target not found: {plan.target_page}")
    content = target.read_text(encoding="utf-8")
    existing = ""
    for line in content.split("\n"):
        if line.strip() and not line.startswith(("#", ">", "[^", "---")):
            existing = line.strip()
            break
    return stage_hedge(
        staged, workspace_path, rel,
        plan.section_heading, existing, body[:500],
        cite_path, f'[^hedge]: {cite_path}',
    )


def _ensure_in_raw(workspace_path: Path, source_file: Path, content: str) -> Path:
    """Copy a source file to raw/local/ if not already there.

    For PDFs, copies the original binary and saves extracted markdown alongside.
    """
    raw_local = workspace_path / "raw" / "local"
    raw_local.mkdir(parents=True, exist_ok=True)

    is_pdf = source_file.suffix.lower() == ".pdf"

    if is_pdf:
        # Copy the original PDF binary
        pdf_dest = raw_local / source_file.name
        if not pdf_dest.exists():
            import shutil
            shutil.copy2(str(source_file), str(pdf_dest))
        # Save extracted markdown with .md extension
        dest = raw_local / (source_file.stem + ".md")
    else:
        dest = raw_local / source_file.name

    if dest.exists():
        existing_hash = hashlib.sha256(dest.read_bytes()).hexdigest()
        new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if existing_hash == new_hash:
            return dest
        stem = dest.stem
        suffix = dest.suffix
        counter = 2
        while dest.exists():
            dest = raw_local / f"{stem}-{counter}{suffix}"
            counter += 1

    dest.write_text(content, encoding="utf-8")
    return dest


def _infer_topic(source_file: Path) -> str:
    """Infer a topic directory name from the source file path."""
    parent = source_file.parent.name
    if parent and parent not in (".", "local", "raw"):
        return parent
    return "concepts"


def _extract_title_from_content(content: str) -> str | None:
    """Extract the best title from the content.

    Prefers a heading that looks like a document title (longer, descriptive)
    over navigation headings (short, generic).
    """
    headings: list[str] = []
    for line in content.strip().split("\n")[:50]:
        line = line.strip()
        if line.startswith("# ") and len(line) > 3:
            title = line.lstrip("#").strip()
            # Skip titles that start with navigation artifacts
            if title and not title.startswith("-") and not title.startswith("["):
                headings.append(title)

    if not headings:
        return None

    # Prefer headings that contain "Title:" (arxiv pattern)
    for h in headings:
        if h.lower().startswith("title:"):
            return h[6:].strip()

    # Prefer the longest heading (likely the actual title, not a section name)
    return max(headings, key=len)


def _extract_body(content: str) -> str:
    """Extract a body summary from the source content."""
    lines = content.strip().split("\n")

    # Skip title, metadata block (- key: value), and --- separator
    start = 0
    in_meta = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            in_meta = True
            start = i + 1
            continue
        if in_meta and (stripped.startswith("- ") or stripped == "" or stripped == "---"):
            start = i + 1
            if stripped == "---":
                in_meta = False
            continue
        if in_meta:
            in_meta = False
        if stripped:
            start = i
            break

    body_lines = [line for line in lines[start:] if not line.startswith("[^")]
    body = "\n".join(body_lines).strip()
    if len(body) > 3000:
        body = body[:3000] + "\n\n... (content continues in raw source)"
    return body


def _extract_representative_quote(content: str) -> str | None:
    """Find a substantial sentence from the source to use as a citation quote."""
    lines = content.strip().split("\n")
    for line in lines:
        line = line.strip()
        # Skip headings, empty lines, and very short lines
        if line.startswith("#") or not line or len(line) < 30:
            continue
        # Skip metadata lines
        if line.startswith(">") or line.startswith("["):
            continue
        # Return the first substantial sentence
        if len(line) > 30:
            # Truncate to ~100 chars if very long
            if len(line) > 100:
                # Find a natural break point
                end = line.find(".", 60)
                if end > 0:
                    return line[: end + 1]
                return line[:100]
            return line
    return None


def _extract_pdf_content(source_file: Path) -> str:
    """Extract text from a PDF file and return as markdown."""
    from alexandria.core.pdf import PDFExtractionError, pdf_to_markdown
    try:
        return pdf_to_markdown(source_file)
    except PDFExtractionError as exc:
        raise IngestError(str(exc)) from exc
