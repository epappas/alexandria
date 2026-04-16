"""Tests for the belief system — extraction, sidecar, repository, and why."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alexandria.core.beliefs.model import Belief
from alexandria.core.beliefs.extractor import extract_beliefs_from_page
from alexandria.core.beliefs.sidecar import read_sidecar, sidecar_path, write_sidecar
from alexandria.core.beliefs.repository import (
    BeliefQuery,
    get_belief,
    insert_belief,
    list_beliefs,
    query_beliefs,
    supersede_belief,
)
from alexandria.db.connection import connect
from alexandria.db.migrator import Migrator


WIKI_PAGE = """\
# Authentication Architecture

> Sources: Acme API Spec v1, 2026-01-10
> Raw: [acme-api-v1](../../raw/local/acme-api-v1.md)

## Overview

Acme uses OAuth 2.0 with JWT tokens for authentication.[^1]

## Endpoints

The refresh endpoint is at /oauth/refresh.[^2]

[^1]: acme-api-v1.md — "The auth layer uses OAuth 2.0 with JWT."
[^2]: acme-api-v1.md — "Token refresh is served at the path /oauth/refresh."
"""


@pytest.fixture
def db(tmp_path: Path):
    """Real SQLite with all migrations applied."""
    db_file = tmp_path / "state.db"
    with connect(db_file) as conn:
        Migrator().apply_pending(conn)
        # Insert a workspace for FK — executescript left no active transaction,
        # so we start a fresh one for the INSERT.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO workspaces (slug, name, path, created_at, updated_at) "
            "VALUES ('research', 'Research', '/tmp/ws', '2026-04-16', '2026-04-16')"
        )
        conn.execute("COMMIT")
        yield conn


class TestBeliefExtraction:
    def test_extracts_beliefs_from_page(self) -> None:
        beliefs = extract_beliefs_from_page(
            WIKI_PAGE, "wiki/concepts/auth.md", "research", "auth"
        )
        assert len(beliefs) >= 2
        statements = [b.statement for b in beliefs]
        assert any("OAuth 2.0" in s for s in statements)
        assert any("refresh" in s.lower() for s in statements)

    def test_beliefs_have_footnote_ids(self) -> None:
        beliefs = extract_beliefs_from_page(
            WIKI_PAGE, "wiki/concepts/auth.md", "research", "auth"
        )
        for b in beliefs:
            assert len(b.footnote_ids) >= 1

    def test_beliefs_have_topic_and_path(self) -> None:
        beliefs = extract_beliefs_from_page(
            WIKI_PAGE, "wiki/concepts/auth.md", "research", "auth"
        )
        for b in beliefs:
            assert b.topic == "auth"
            assert b.wiki_document_path == "wiki/concepts/auth.md"

    def test_extracts_structured_fields(self) -> None:
        beliefs = extract_beliefs_from_page(
            WIKI_PAGE, "wiki/concepts/auth.md", "research", "auth"
        )
        oauth_belief = next((b for b in beliefs if "OAuth" in b.statement), None)
        assert oauth_belief is not None
        # Best-effort structured extraction
        assert oauth_belief.subject is not None or oauth_belief.predicate is not None

    def test_no_beliefs_from_plain_text(self) -> None:
        beliefs = extract_beliefs_from_page(
            "# Title\n\nNo citations here.\n", "page.md", "ws", "topic"
        )
        assert beliefs == []


class TestSidecar:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        page = tmp_path / "auth.md"
        page.write_text("# Auth\n", encoding="utf-8")

        beliefs = [
            Belief(
                workspace="research",
                statement="Acme uses OAuth 2.0",
                topic="auth",
                wiki_document_path="wiki/concepts/auth.md",
                footnote_ids=["1"],
            ),
        ]
        write_sidecar(page, beliefs)

        path = sidecar_path(page)
        assert path.exists()
        assert path.name == "auth.beliefs.json"

        loaded = read_sidecar(page, workspace="research")
        assert len(loaded) == 1
        assert loaded[0].statement == "Acme uses OAuth 2.0"
        assert loaded[0].topic == "auth"

    def test_read_missing_sidecar(self, tmp_path: Path) -> None:
        page = tmp_path / "missing.md"
        result = read_sidecar(page)
        assert result == []


class TestBeliefRepository:
    def test_insert_and_get(self, db) -> None:
        belief = Belief(
            workspace="research",
            statement="Acme uses OAuth 2.0",
            topic="auth",
            wiki_document_path="wiki/concepts/auth.md",
            footnote_ids=["1"],
        )
        db.execute("BEGIN IMMEDIATE")
        insert_belief(db, belief)
        db.execute("COMMIT")

        fetched = get_belief(db, belief.belief_id)
        assert fetched is not None
        assert fetched.statement == "Acme uses OAuth 2.0"
        assert fetched.workspace == "research"
        assert fetched.is_current

    def test_list_beliefs_by_topic(self, db) -> None:
        for i in range(3):
            b = Belief(
                workspace="research",
                statement=f"Claim {i}",
                topic="auth",
                wiki_document_path=f"wiki/concepts/auth{i}.md",
            )
            db.execute("BEGIN IMMEDIATE")
            insert_belief(db, b)
            db.execute("COMMIT")

        results = list_beliefs(db, "research", topic="auth")
        assert len(results) == 3

    def test_supersede_belief(self, db) -> None:
        old = Belief(
            workspace="research",
            statement="Endpoint is /oauth/refresh",
            topic="auth",
            wiki_document_path="wiki/concepts/auth.md",
            footnote_ids=["1"],
        )
        new = Belief(
            workspace="research",
            statement="Endpoint moved to /auth/v2/refresh",
            topic="auth",
            wiki_document_path="wiki/concepts/auth.md",
            footnote_ids=["2"],
        )
        db.execute("BEGIN IMMEDIATE")
        insert_belief(db, old)
        insert_belief(db, new)
        supersede_belief(db, old.belief_id, new.belief_id, reason="contradicted_by_new_source")
        db.execute("COMMIT")

        old_fetched = get_belief(db, old.belief_id)
        assert old_fetched is not None
        assert not old_fetched.is_current
        assert old_fetched.superseded_by_belief_id == new.belief_id
        assert old_fetched.supersession_reason == "contradicted_by_new_source"

        new_fetched = get_belief(db, new.belief_id)
        assert new_fetched is not None
        assert new_fetched.is_current

    def test_list_current_only(self, db) -> None:
        old = Belief(workspace="research", statement="Old claim", topic="auth",
                     wiki_document_path="wiki/auth.md")
        new = Belief(workspace="research", statement="New claim", topic="auth",
                     wiki_document_path="wiki/auth.md")
        db.execute("BEGIN IMMEDIATE")
        insert_belief(db, old)
        insert_belief(db, new)
        supersede_belief(db, old.belief_id, new.belief_id)
        db.execute("COMMIT")

        current = list_beliefs(db, "research", current_only=True)
        assert len(current) == 1
        assert current[0].statement == "New claim"

        all_beliefs = list_beliefs(db, "research", current_only=False)
        assert len(all_beliefs) == 2

    def test_fts_query(self, db) -> None:
        b = Belief(
            workspace="research",
            statement="Quantum computing uses qubits for superposition",
            topic="physics",
            wiki_document_path="wiki/physics/qc.md",
        )
        db.execute("BEGIN IMMEDIATE")
        insert_belief(db, b)
        db.execute("COMMIT")

        results = query_beliefs(db, BeliefQuery(
            workspace="research", query="quantum superposition"
        ))
        assert len(results) >= 1
        assert any("quantum" in r.statement.lower() for r in results)


class TestBeliefModel:
    def test_auto_generates_id_and_timestamps(self) -> None:
        b = Belief(workspace="ws", statement="test", topic="t", wiki_document_path="p.md")
        assert b.belief_id.startswith("b-")
        assert len(b.belief_id) > 5
        assert b.created_at
        assert b.asserted_at

    def test_is_current_when_not_superseded(self) -> None:
        b = Belief(workspace="ws", statement="test", topic="t", wiki_document_path="p.md")
        assert b.is_current

    def test_not_current_when_superseded(self) -> None:
        b = Belief(
            workspace="ws", statement="test", topic="t", wiki_document_path="p.md",
            superseded_at="2026-04-16",
        )
        assert not b.is_current

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        b = Belief(
            workspace="ws", statement="test claim", topic="auth",
            wiki_document_path="p.md", subject="Acme", predicate="uses", object="OAuth",
            footnote_ids=["1", "2"],
        )
        d = b.to_dict()
        restored = Belief.from_dict(d, workspace="ws")
        assert restored.statement == b.statement
        assert restored.subject == b.subject
        assert restored.footnote_ids == b.footnote_ids
