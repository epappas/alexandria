"""Tests for ``alexandria.core.workspace`` against real filesystem + SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.core.workspace import (
    GLOBAL_SLUG,
    InvalidSlugError,
    WorkspaceError,
    WorkspaceExistsError,
    WorkspaceNotFoundError,
    delete_workspace,
    get_workspace,
    init_workspace,
    list_workspaces,
    rename_workspace,
    validate_slug,
)


def test_validate_slug_accepts_simple_slug() -> None:
    validate_slug("research")
    validate_slug("customer-acme")
    validate_slug("project_2026")


@pytest.mark.parametrize(
    "bad",
    ["", "Research", "-leading", "with space", "very-long-" * 10, "uppercase_BAD"],
)
def test_validate_slug_rejects_invalid(bad: str) -> None:
    with pytest.raises(InvalidSlugError):
        validate_slug(bad)


def test_init_creates_directory_and_files(initialized_home: Path) -> None:
    ws = init_workspace(initialized_home, slug="research", name="Research")
    assert ws.path.exists()
    assert ws.raw_dir.exists()
    assert ws.wiki_dir.exists()
    assert ws.skill_path.exists()
    assert ws.identity_path.exists()
    assert ws.config_path.exists()


def test_init_then_get_returns_same_workspace(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="research", name="Research", description="ML papers")
    ws = get_workspace(initialized_home, "research")
    assert ws.slug == "research"
    assert ws.name == "Research"
    assert ws.description == "ML papers"


def test_init_duplicate_raises(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="research", name="Research")
    with pytest.raises(WorkspaceExistsError):
        init_workspace(initialized_home, slug="research", name="Research")


def test_get_missing_raises(initialized_home: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        get_workspace(initialized_home, "nonexistent")


def test_list_includes_global_workspace(initialized_home: Path) -> None:
    workspaces = list_workspaces(initialized_home)
    slugs = [w.slug for w in workspaces]
    assert GLOBAL_SLUG in slugs


def test_list_returns_sorted(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="zebra", name="Zebra")
    init_workspace(initialized_home, slug="apple", name="Apple")
    workspaces = list_workspaces(initialized_home)
    slugs = [w.slug for w in workspaces]
    assert slugs == sorted(slugs)


def test_delete_moves_to_trash(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="temp", name="Temp")
    assert (initialized_home / "workspaces" / "temp").exists()
    target = delete_workspace(initialized_home, "temp")
    assert not (initialized_home / "workspaces" / "temp").exists()
    assert target.exists()
    assert target.parent == initialized_home / ".trash"
    with pytest.raises(WorkspaceNotFoundError):
        get_workspace(initialized_home, "temp")


def test_delete_global_refused(initialized_home: Path) -> None:
    with pytest.raises(WorkspaceError):
        delete_workspace(initialized_home, GLOBAL_SLUG)


def test_rename_moves_directory_and_updates_db(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="old", name="Old")
    new = rename_workspace(initialized_home, "old", "new")
    assert new.slug == "new"
    assert (initialized_home / "workspaces" / "new").exists()
    assert not (initialized_home / "workspaces" / "old").exists()


def test_rename_global_refused(initialized_home: Path) -> None:
    with pytest.raises(WorkspaceError):
        rename_workspace(initialized_home, GLOBAL_SLUG, "another")


def test_rename_to_existing_refused(initialized_home: Path) -> None:
    init_workspace(initialized_home, slug="one", name="One")
    init_workspace(initialized_home, slug="two", name="Two")
    with pytest.raises(WorkspaceExistsError):
        rename_workspace(initialized_home, "one", "two")
