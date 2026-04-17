"""``alexandria ingest`` — the core ingest pipeline.

Reads a raw source, stages wiki writes via cascade operations, runs the
verifier, and commits or rejects. This is the complete write path from
``04_guardian_agent.md``.

Phase 2b ships the basic ingest for local markdown files. Source adapters
(GitHub, RSS, etc.) arrive in Phase 4+.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alexandria.core.cascade import stage_new_page
from alexandria.core.citations import extract_footnotes
from alexandria.core.runs import (
    RunStatus,
    commit_run,
    create_run,
    get_staged_dir,
    reject_run,
    update_run_status,
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

    # Ensure the source is in raw/ (skip if already there, e.g. from fetch_and_save)
    raw_dir = workspace_path / "raw"
    if source_file.resolve().is_relative_to(raw_dir.resolve()):
        raw_dest = source_file
    else:
        raw_dest = _ensure_in_raw(workspace_path, source_file, source_content)

    # Create a run
    run = create_run(home, workspace_slug, f"cli:ingest", "ingest")

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
    title = source_file.stem.replace("-", " ").replace("_", " ").title()

    # Extract any existing footnotes from the source for pass-through
    footnotes = extract_footnotes(source_content)
    footnote_lines = "\n".join(fn.raw_line for fn in footnotes) if footnotes else ""

    # Build the wiki page content
    raw_rel = raw_dest.relative_to(workspace_path)
    sources_line = f"{title}, {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    raw_line = f"[{source_file.name}](../../{raw_rel})"

    # Use a summary of the source as the body (in Phase 2b, the LLM would
    # generate this; for now, use the first ~2000 chars as the body)
    body = _extract_body(source_content)

    # If no footnotes exist in source, create one citing the raw destination
    # Use the relative path from workspace root so verifier + lint can find it
    cite_path = str(raw_dest.relative_to(workspace_path))
    if not footnote_lines:
        quote = _extract_representative_quote(source_content)
        if quote:
            footnote_lines = f'[^1]: {cite_path} — "{quote}"'
            body += " [^1]"

    staged_path = stage_new_page(
        staged,
        topic=resolved_topic,
        slug=slug,
        title=title,
        body=body,
        sources_line=sources_line,
        raw_line=raw_line,
        footnotes=footnote_lines,
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
                        ended_at=datetime.now(timezone.utc).isoformat(),
                    )

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
                                   content_hash, size_bytes, title, created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                        datetime('now'), datetime('now'))""",
                                (
                                    doc_id, workspace_slug, "wiki",
                                    f"wiki/{rel_path}", Path(rel_path).name, "md",
                                    wiki_content, wiki_hash, len(wiki_content), title,
                                ),
                            )

                    # Also register the raw source
                    raw_rel = raw_dest.relative_to(workspace_path)
                    raw_doc_id = f"doc-{hashlib.sha256(str(raw_rel).encode()).hexdigest()[:12]}"
                    conn.execute(
                        """INSERT OR REPLACE INTO documents
                          (id, workspace, layer, path, filename, file_type, content,
                           content_hash, size_bytes, title, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                datetime('now'), datetime('now'))""",
                        (
                            raw_doc_id, workspace_slug, "raw",
                            str(raw_rel), raw_dest.name,
                            source_file.suffix.lstrip(".") or "md",
                            source_content, hashlib.sha256(source_content.encode()).hexdigest(),
                            len(source_content), title,
                        ),
                    )

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

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
                    ended_at=datetime.now(timezone.utc).isoformat(),
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


def _extract_body(content: str) -> str:
    """Extract a body summary from the source content."""
    lines = content.strip().split("\n")
    # Skip the title line if present
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("#"):
            start = i + 1
            break

    body_lines = [l for l in lines[start:] if not l.startswith("[^")]
    body = "\n".join(body_lines).strip()
    if len(body) > 2000:
        body = body[:2000] + "\n\n... (content continues in raw source)"
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
    from alexandria.core.pdf import pdf_to_markdown, PDFExtractionError
    try:
        return pdf_to_markdown(source_file)
    except PDFExtractionError as exc:
        raise IngestError(str(exc)) from exc
