"""End-to-end integration test: init -> paste -> ingest -> query -> why -> lint -> synthesize."""

import json
import os
from pathlib import Path

import pytest

from alexandria.config import resolve_home
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Set up a complete alexandria home for E2E testing."""
    h = tmp_path / "alexandria_home"
    os.environ["ALEXANDRIA_HOME"] = str(h)

    # Initialize
    from alexandria.core.workspace import init_workspace
    from alexandria.config import write_default_config

    h.mkdir(parents=True)
    write_default_config(h)
    with connect(db_path(h)) as conn:
        Migrator().apply_pending(conn)

    init_workspace(h, "global", "Global", "Global workspace")
    init_workspace(h, "test-project", "Test Project", "E2E test project")

    yield h

    # Cleanup
    os.environ.pop("ALEXANDRIA_HOME", None)


@pytest.fixture
def workspace_path(home: Path) -> Path:
    return home / "workspaces" / "test-project"


class TestEndToEndFlow:
    def test_full_knowledge_cycle(self, home: Path, workspace_path: Path) -> None:
        """Test the complete knowledge lifecycle:
        1. Create a raw source
        2. Verify it appears in queries
        3. Check lint finds no issues
        4. Run synthesis
        """
        # Step 1: Create a raw source document
        raw_dir = workspace_path / "raw" / "local"
        raw_dir.mkdir(parents=True, exist_ok=True)
        source_file = raw_dir / "architecture_notes.md"
        source_file.write_text(
            "# Architecture Notes\n\n"
            "The system uses SQLite with WAL mode for concurrent reads.\n"
            "All wiki pages must cite their raw sources via footnotes.\n"
            "The hostile verifier checks every wiki write before commit.\n",
            encoding="utf-8",
        )

        # Step 2: Create a wiki page that cites the source
        wiki_dir = workspace_path / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        wiki_page = wiki_dir / "architecture.md"
        wiki_page.write_text(
            "# Architecture\n\n"
            "alexandria uses SQLite with WAL mode [^1].\n"
            "Every wiki write goes through the hostile verifier [^2].\n\n"
            "[^1]: raw/local/architecture_notes.md — \"SQLite with WAL mode\"\n"
            "[^2]: raw/local/architecture_notes.md — \"hostile verifier checks every wiki write\"\n",
            encoding="utf-8",
        )

        # Step 3: Register the document in the database
        with connect(db_path(home)) as conn:
            import hashlib
            content = source_file.read_text()
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO documents
                  (id, workspace, layer, path, filename, file_type, content,
                   content_hash, size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (
                    "doc-raw-1", "test-project", "raw",
                    "raw/local/architecture_notes.md", "architecture_notes.md",
                    "md", content, content_hash, len(content),
                ),
            )
            wiki_content = wiki_page.read_text()
            wiki_hash = hashlib.sha256(wiki_content.encode()).hexdigest()
            conn.execute(
                """INSERT INTO documents
                  (id, workspace, layer, path, filename, file_type, content,
                   content_hash, size_bytes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (
                    "doc-wiki-1", "test-project", "wiki",
                    "wiki/architecture.md", "architecture.md",
                    "md", wiki_content, wiki_hash, len(wiki_content),
                ),
            )
            conn.execute("COMMIT")

        # Step 4: Extract beliefs from the wiki page
        from alexandria.core.beliefs.extractor import extract_beliefs_from_page
        from alexandria.core.beliefs.repository import insert_belief

        beliefs = extract_beliefs_from_page(
            wiki_content, "wiki/architecture.md", "test-project", "architecture"
        )
        assert len(beliefs) >= 1, "Should extract at least one belief from cited content"

        with connect(db_path(home)) as conn:
            for belief in beliefs:
                conn.execute("BEGIN IMMEDIATE")
                insert_belief(conn, belief)
                conn.execute("COMMIT")

        # Step 5: Verify beliefs were stored and are queryable
        with connect(db_path(home)) as conn:
            belief_rows = conn.execute(
                "SELECT statement, topic FROM wiki_beliefs WHERE workspace = ?",
                ("test-project",),
            ).fetchall()
            assert len(belief_rows) >= 1, "Should have at least one belief"

            # Verify FTS is populated
            fts_rows = conn.execute(
                "SELECT statement FROM wiki_beliefs_fts WHERE wiki_beliefs_fts MATCH 'SQLite'"
            ).fetchall()
            assert len(fts_rows) >= 1, f"FTS should find SQLite, beliefs: {[r['statement'] for r in belief_rows]}"

        # Step 6: Lint should find no errors (sources exist, citations valid)
        from alexandria.cli.lint_cmd import _scan_workspace
        issues = _scan_workspace(workspace_path, home, "test-project", verbose=False)
        errors = [i for i in issues if i["severity"] == "error"]
        assert len(errors) == 0, f"Lint should find no errors, got: {errors}"

        # Step 7: Synthesis should produce a digest (or skip if no events)
        from alexandria.core.synthesis import run_synthesis
        with connect(db_path(home)) as conn:
            synth_result = run_synthesis(conn, "test-project", workspace_path)
        # May be "skipped" (no events) or "completed" — both are valid
        assert synth_result["status"] in ("skipped", "completed")

        # Step 8: Eval metrics should run without error
        from alexandria.eval.runner import run_all_metrics
        with connect(db_path(home)) as conn:
            eval_results = run_all_metrics(conn, "test-project")
        assert len(eval_results) >= 4, "Should run M1, M2, M4, M5"
        for r in eval_results:
            assert r.score >= 0.0, f"{r.metric} score should be non-negative"

    def test_workspace_lifecycle(self, home: Path) -> None:
        """Test workspace create, list, rename, delete."""
        from alexandria.core.workspace import (
            get_workspace,
            list_workspaces,
            rename_workspace,
            delete_workspace,
        )

        workspaces = list_workspaces(home)
        names = [ws.slug for ws in workspaces]
        assert "global" in names
        assert "test-project" in names

        # Rename
        rename_workspace(home, "test-project", "renamed-project")
        ws = get_workspace(home, "renamed-project")
        assert ws.slug == "renamed-project"

        # Delete
        delete_workspace(home, "renamed-project")
        workspaces = list_workspaces(home)
        assert "renamed-project" not in [ws.slug for ws in workspaces]

    def test_migrations_all_apply(self, home: Path) -> None:
        """Verify all 8 migrations applied cleanly."""
        with connect(db_path(home)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == 8

            # Check key tables exist
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            expected = {
                "workspaces", "documents", "documents_fts",
                "runs", "wiki_claim_provenance",
                "wiki_beliefs", "wiki_beliefs_fts",
                "source_adapters", "source_runs",
                "events", "events_fts",
                "subscription_items", "subscription_items_fts",
                "mcp_session_log", "capture_queue",
                "eval_runs", "eval_gold_queries",
                "daemon_heartbeats", "schema_migrations",
            }
            missing = expected - tables
            assert not missing, f"Missing tables: {missing}"
