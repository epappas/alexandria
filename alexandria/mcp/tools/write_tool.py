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
    def ingest(
        source: str,
        workspace: str | None = None,
        topic: str | None = None,
    ) -> str:
        """Ingest a source into the knowledge base.

        Accepts any of:
        - URL (fetches page/PDF, extracts content)
        - Git repo URL or GitHub shorthand ``owner/repo`` (clones and ingests all files)
        - Local file path
        - Local directory path (ingests all supported files)
        """
        from pathlib import Path
        from alexandria.config import resolve_home
        from alexandria.core.ingest import ingest_file, IngestError
        from alexandria.cli.ingest_cmd import _is_git_url, _is_github_shorthand

        ws_path, slug = resolve(workspace)
        home = resolve_home()

        # GitHub shorthand
        if _is_github_shorthand(source):
            source = f"https://github.com/{source}.git"

        # Git repo
        if _is_git_url(source):
            from alexandria.core.repo_ingest import clone_repo, ingest_repo
            try:
                repo_path = clone_repo(source, ws_path / "raw" / "git")
            except IngestError as exc:
                return f"Clone failed: {exc}"
            result = ingest_repo(
                home=home, workspace_slug=slug, workspace_path=ws_path,
                repo_path=repo_path, topic=topic,
            )
            return _format_repo_result(source, result)

        # HTTP URL (non-git)
        if source.startswith(("http://", "https://")):
            from alexandria.core.web import fetch_and_save, WebFetchError
            try:
                source_path = fetch_and_save(source, ws_path)
            except WebFetchError as exc:
                return f"Fetch failed: {exc}"
            try:
                r = ingest_file(home, slug, ws_path, source_path, topic=topic)
            except IngestError as exc:
                return f"Ingest failed: {exc}"
            if r.committed:
                return f"Ingested: {source}\nWiki: {', '.join(r.committed_paths)}"
            return f"Rejected: {r.verdict_reasoning}"

        # Local path
        local = Path(source).expanduser().resolve()
        if not local.exists():
            return f"Not found: {source}"

        # Directory
        if local.is_dir():
            from alexandria.core.repo_ingest import ingest_repo
            result = ingest_repo(
                home=home, workspace_slug=slug, workspace_path=ws_path,
                repo_path=local, topic=topic,
            )
            return _format_repo_result(source, result)

        # JSONL conversation transcript
        if local.suffix == ".jsonl":
            from alexandria.core.capture.conversation import (
                capture_conversation, detect_format, CaptureError,
            )
            fmt = detect_format(local)
            if fmt != "unknown":
                try:
                    cap = capture_conversation(local, ws_path, client=fmt)
                except CaptureError as exc:
                    return f"Capture failed: {exc}"
                md_path = Path(cap["absolute_path"])
                try:
                    r = ingest_file(home, slug, ws_path, md_path, topic=topic or "conversations")
                except IngestError as exc:
                    return f"Ingest failed: {exc}"
                lines = []
                if r.committed:
                    lines.append(f"Conversation captured: {cap['message_count']} messages")
                    lines.append(f"Wiki: {', '.join(r.committed_paths)}")
                else:
                    lines.append(f"Conversation rejected: {r.verdict_reasoning}")

                # Ingest referenced artifacts
                from alexandria.core.capture.artifacts import extract_artifacts
                from alexandria.core.capture.conversation import _parse_claude_code_jsonl
                from alexandria.core.web import fetch_and_save, WebFetchError

                raw_msgs = _parse_claude_code_jsonl(local) if fmt == "claude-code" else []
                artifacts = extract_artifacts(raw_msgs)
                art_ok = 0
                for art in artifacts:
                    try:
                        art_path = fetch_and_save(art.url, ws_path)
                        ar = ingest_file(home, slug, ws_path, art_path, topic=topic or "research")
                        if ar.committed:
                            art_ok += 1
                    except Exception:
                        continue
                if artifacts:
                    lines.append(f"Artifacts: {art_ok}/{len(artifacts)} ingested")
                return "\n".join(lines)

        # Single file
        try:
            r = ingest_file(home, slug, ws_path, local, topic=topic)
        except IngestError as exc:
            return f"Ingest failed: {exc}"
        if r.committed:
            return f"Ingested: {local.name}\nWiki: {', '.join(r.committed_paths)}"
        return f"Rejected: {r.verdict_reasoning}"

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

    def _format_repo_result(source: str, result: "RepoIngestResult") -> str:
        from alexandria.core.repo_ingest import RepoIngestResult
        lines = [f"Ingested: {source}", f"Committed: {len(result.committed)} files"]
        if result.rejected:
            lines.append(f"Rejected: {len(result.rejected)}")
        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
            for err in result.errors[:3]:
                lines.append(f"  {err}")
        if result.committed:
            lines.append(f"\nPages: {', '.join(result.committed[:10])}")
        return "\n".join(lines)
