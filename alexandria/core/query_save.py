"""Save query answers as wiki pages.

Closes the knowledge compounding loop: answers become searchable,
citable sources for future queries.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alexandria.core.cascade import stage_new_page
from alexandria.core.ingest import IngestResult
from alexandria.core.runs import commit_run, create_run, get_staged_dir


def save_query_as_page(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    question: str,
    result: dict[str, Any],
    conn: sqlite3.Connection,
) -> IngestResult:
    """Save a query answer as a wiki page in wiki/queries/."""
    answer = result.get("answer", "")
    sources = result.get("sources", [])
    if not answer.strip():
        return IngestResult(
            run_id="", committed=False, committed_paths=[],
            verdict_reasoning="empty answer", source_path="",
        )

    slug = _question_to_slug(question)
    title = question.strip().rstrip("?") if len(question) < 100 else question[:97] + "..."

    # Build footnotes from sources
    footnotes = "\n".join(
        f"[^{i+1}]: {s.get('path', '')}" for i, s in enumerate(sources)
    )

    # Build body with query metadata
    body = f"> Query: {question}\n\n{answer}"

    run = create_run(home, workspace_slug, "cli:query-save", "query-save")
    staged = get_staged_dir(home, run.run_id)

    now = datetime.now(UTC)
    stage_new_page(
        staged, topic="queries", slug=slug, title=title, body=body,
        sources_line=f"Query answer, {now.strftime('%Y-%m-%d')}",
        raw_line="(generated from query)",
        footnotes=footnotes,
    )

    committed_paths = commit_run(home, run.run_id, workspace_path)

    # Register in documents table for FTS
    conn.execute("BEGIN IMMEDIATE")
    try:
        for rel_path in committed_paths:
            wiki_file = workspace_path / "wiki" / rel_path
            if not wiki_file.exists():
                continue
            content = wiki_file.read_text(encoding="utf-8")
            doc_id = f"doc-{hashlib.sha256(rel_path.encode()).hexdigest()[:12]}"
            conn.execute(
                """INSERT OR REPLACE INTO documents
                  (id, workspace, layer, path, filename, file_type, content,
                   content_hash, size_bytes, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (doc_id, workspace_slug, "wiki", f"wiki/{rel_path}",
                 Path(rel_path).name, "md", content,
                 hashlib.sha256(content.encode()).hexdigest(),
                 len(content), title),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return IngestResult(
        run_id=run.run_id, committed=True,
        committed_paths=committed_paths,
        verdict_reasoning="query answer saved",
        source_path=question,
    )


def _question_to_slug(question: str) -> str:
    """Convert a question to a filesystem-safe slug."""
    slug = re.sub(r'[^a-z0-9\s-]', '', question.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    return slug[:60] or "query"
