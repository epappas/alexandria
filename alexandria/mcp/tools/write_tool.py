"""MCP write tools — allow agents to correct beliefs and add knowledge."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: "FastMCP", resolve: "WorkspaceResolver") -> None:
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
        from alexandria.db.connection import connect, db_path
        from alexandria.core.beliefs.model import Belief
        from alexandria.core.beliefs.repository import insert_belief

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
        from alexandria.db.connection import connect, db_path
        from alexandria.core.beliefs.model import Belief
        from alexandria.core.beliefs.repository import (
            get_belief, insert_belief, supersede_belief,
        )

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
    def ingest_url(
        url: str,
        workspace: str | None = None,
        topic: str | None = None,
    ) -> str:
        """Ingest a URL into the knowledge base.

        Fetches the page, extracts content, runs the verifier, and
        commits to the wiki. If an LLM is configured, produces a
        summary with structured beliefs.
        """
        from alexandria.config import resolve_home, load_config, resolve_workspace
        from alexandria.core.workspace import get_workspace
        from alexandria.core.web import fetch_and_save, WebFetchError
        from alexandria.core.ingest import ingest_file, IngestError

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        try:
            source_path = fetch_and_save(url, ws_path)
        except WebFetchError as exc:
            return f"Fetch failed: {exc}"

        try:
            ws = get_workspace(home, slug)
            result = ingest_file(home, slug, ws.path, source_path, topic=topic)
        except IngestError as exc:
            return f"Ingest failed: {exc}"

        if result.committed:
            return (
                f"Ingested: {url}\n"
                f"Wiki page: {', '.join(result.committed_paths)}\n"
                f"Run: {result.run_id}"
            )
        return f"Rejected: {result.verdict_reasoning}"

    @mcp.tool()
    def ingest_repo(
        source: str,
        workspace: str | None = None,
        topic: str | None = None,
    ) -> str:
        """Ingest all supported files from a git repo or local directory.

        Accepts a git URL (GitHub, GitLab) or local path. Git URLs are
        shallow-cloned automatically. Walks the tree and ingests code
        files (.py, .ts, .rs, .go, .tf, .yml), docs (.md), and configs.
        """
        from alexandria.config import resolve_home
        from alexandria.core.workspace import get_workspace
        from alexandria.core.repo_ingest import (
            clone_repo, ingest_repo as _ingest_repo, IngestError,
        )
        from alexandria.cli.ingest_repo_cmd import _is_git_url

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        if _is_git_url(source):
            try:
                git_dir = ws_path / "raw" / "git"
                repo_path = clone_repo(source, git_dir)
            except IngestError as exc:
                return f"Clone failed: {exc}"
        else:
            from pathlib import Path
            repo_path = Path(source).expanduser().resolve()
            if not repo_path.is_dir():
                return f"Not a directory: {source}"

        result = _ingest_repo(
            home=home,
            workspace_slug=slug,
            workspace_path=ws_path,
            repo_path=repo_path,
            topic=topic,
        )

        lines = [f"Ingested repo: {source}"]
        lines.append(f"Committed: {len(result.committed)} files")
        if result.rejected:
            lines.append(f"Rejected: {len(result.rejected)}")
        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
            for err in result.errors[:3]:
                lines.append(f"  {err}")
        if result.committed:
            lines.append(f"\nPages: {', '.join(result.committed[:10])}")
        return "\n".join(lines)

    @mcp.tool()
    def query(
        question: str,
        workspace: str | None = None,
    ) -> str:
        """Answer a question by navigating the knowledge base.

        Spawns Alexandria's internal agent loop which uses search, grep,
        read, and beliefs to find relevant content and synthesize an
        answer with citations. Use this for complex questions that
        require exploring multiple sources.
        """
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path
        from alexandria.core.agent_loop import run_agent_query

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
        return answer + source_text
