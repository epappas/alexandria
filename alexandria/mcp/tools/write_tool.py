"""MCP write tools — allow agents to correct beliefs and add knowledge."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:
    @mcp.tool()
    def belief_add(
        statement: str,
        topic: str,
        workspace: str | None = None,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        wiki_page: str | None = None,
        footnote_ids: str | None = None,
    ) -> str:
        """Add or correct a belief in the knowledge base.

        Use this when you've identified a factual claim that should be
        recorded, or when correcting an existing belief. The belief will
        be stored with provenance linking it to the source.
        """
        from alexandria.config import resolve_home
        from alexandria.core.beliefs.model import Belief
        from alexandria.core.beliefs.repository import insert_belief
        from alexandria.db.connection import connect, db_path

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        fn_ids = [f.strip() for f in footnote_ids.split(",")] if footnote_ids else []

        belief = Belief(
            workspace=slug,
            statement=statement[:500],
            topic=topic,
            wiki_document_path=wiki_page or "",
            footnote_ids=fn_ids,
            subject=subject,
            predicate=predicate,
            object=object,
        )

        with connect(db_path(home)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                insert_belief(conn, belief)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return f"Belief added: {belief.belief_id} — {statement[:80]}"

    @mcp.tool()
    def belief_supersede(
        belief_id: str,
        new_statement: str,
        reason: str,
        workspace: str | None = None,
    ) -> str:
        """Supersede an existing belief with a corrected version.

        Use this when a belief is wrong or outdated. The old belief is
        marked as superseded with the reason, and a new belief is created.
        """
        from alexandria.config import resolve_home
        from alexandria.core.beliefs.model import Belief
        from alexandria.core.beliefs.repository import (
            get_belief,
            insert_belief,
            supersede_belief,
        )
        from alexandria.db.connection import connect, db_path

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            old = get_belief(conn, belief_id)
            if not old:
                return f"Belief not found: {belief_id}"

            # Create the replacement belief from the old one
            new_belief = Belief(
                workspace=old.workspace,
                statement=new_statement[:500],
                topic=old.topic,
                subject=old.subject,
                predicate=old.predicate,
                object=old.object,
                wiki_document_path=old.wiki_document_path,
                footnote_ids=old.footnote_ids,
            )

            conn.execute("BEGIN IMMEDIATE")
            try:
                insert_belief(conn, new_belief)
                supersede_belief(conn, belief_id, new_belief.belief_id, reason=reason)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return (
            f"Superseded {belief_id} with {new_belief.belief_id}\n"
            f"Old: {old.statement[:80]}\n"
            f"New: {new_statement[:80]}\n"
            f"Reason: {reason}"
        )

    @mcp.tool()
    def ingest(
        source: str,
        workspace: str | None = None,
        topic: str | None = None,
        no_merge: bool = False,
        scope: str = "all",
        wait_s: int = 60,
    ) -> str:
        """Enqueue an ingest job and optionally wait for it.

        Accepts any of:
        - URL (fetches page/PDF, extracts content)
        - Git repo URL or GitHub shorthand ``owner/repo`` (clones and
          ingests files)
        - Local file path
        - Local directory path (ingests all supported files)

        ``scope='all'`` (default) ingests everything; ``scope='docs'``
        restricts repository ingests to README, top-level markdown, and
        ``docs/`` trees — recommended for large codebases where you only
        want the documentation surfaces.

        ``no_merge=True`` forces a brand-new wiki page per source and
        skips cascade merge/hedge planning.

        ``wait_s`` caps how long the call blocks for the job to finish.
        Short ingests return their full result; long ones return a
        ``job_id`` that the agent should poll via ``jobs_status``.
        Use ``wait_s=0`` to always return a job handle immediately.
        """
        from alexandria.cli.ingest_cmd import (
            _is_bare_url,
            _is_github_shorthand,
        )
        from alexandria.config import resolve_home

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        # GitHub shorthand
        if _is_github_shorthand(source):
            source = f"https://github.com/{source}.git"

        # Bare domain URL (e.g. arxiv.org/abs/...) -> prepend https://
        if _is_bare_url(source):
            source = f"https://{source}"

        return _enqueue_and_maybe_wait(
            home, slug, source,
            topic=topic, no_merge=no_merge, scope=scope, wait_s=wait_s,
        )

    @mcp.tool()
    def query(
        question: str,
        workspace: str | None = None,
        save: bool = False,
    ) -> str:
        """Answer a question by navigating the knowledge base.

        Spawns Alexandria's internal agent loop which uses search, grep,
        read, and beliefs to find relevant content and synthesize an
        answer with citations. Set save=true to persist the answer as
        a wiki page for future reference.
        """
        from alexandria.config import resolve_home
        from alexandria.core.agent_loop import run_agent_query
        from alexandria.db.connection import connect, db_path

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        with connect(db_path(home)) as conn:
            result = run_agent_query(conn, slug, ws_path, question)

        if result is None:
            return "No LLM provider configured. Cannot run agent query."

        answer = result.get("answer", "No answer produced.")
        sources = result.get("sources", [])
        source_text = ""
        if sources:
            source_text = "\n\nSources:\n" + "\n".join(
                f"- {s.get('title', '')} ({s.get('path', '')})" for s in sources
            )

        if save and result:
            from alexandria.core.query_save import save_query_as_page
            with connect(db_path(home)) as conn:
                sr = save_query_as_page(home, slug, ws_path, question, result, conn)
            if sr.committed:
                source_text += f"\n\nSaved to: wiki/{sr.committed_paths[0]}"

        return answer + source_text

    def _enqueue_and_maybe_wait(
        home: Path,  # noqa: F821
        slug: str,
        source: str,
        *,
        topic: str | None,
        no_merge: bool,
        scope: str,
        wait_s: int,
    ) -> str:
        """Enqueue an ingest job; wait up to ``wait_s`` for completion."""
        import time as _time

        from alexandria.db.connection import connect, db_path
        from alexandria.jobs.model import JobStatus
        from alexandria.jobs.queue import enqueue_ingest, get_job

        spec = {
            "source": source,
            "topic": topic,
            "no_merge": no_merge,
            "scope": scope,
        }
        with connect(db_path(home)) as conn:
            job = enqueue_ingest(conn, slug, spec)

        if wait_s <= 0:
            return _format_job_handle(job)

        deadline = _time.time() + wait_s
        while _time.time() < deadline:
            _time.sleep(1.0)
            with connect(db_path(home)) as conn:
                job = get_job(conn, job.job_id)
            if job.status in (
                JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED,
            ):
                return _format_job_final(job)
        return _format_job_handle(job)

    def _format_job_handle(job: object) -> str:  # noqa: ANN001
        return (
            f"Job {job.job_id} {job.status.value} — {job.message or 'waiting'}\n"
            f"Progress: {job.files_done}/{job.files_total} "
            f"({job.progress_pct}%)\n"
            f"Poll with: jobs_status(job_id='{job.job_id}')"
        )

    def _format_job_final(job: object) -> str:  # noqa: ANN001
        lines = [
            f"Job {job.job_id} {job.status.value} — "
            f"{job.message or 'done'}",
            f"Files: {job.files_done} committed"
            + (f", {job.files_failed} failed" if job.files_failed else ""),
        ]
        if job.error:
            lines.append(f"Error: {job.error[:300]}")
        if job.run_ids:
            lines.append(f"Pages: {', '.join(job.run_ids[:10])}")
        return "\n".join(lines)
