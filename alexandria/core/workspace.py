"""Workspace primitives.

A workspace is a directory under ``<alexandria_home>/workspaces/<slug>/`` with a
fixed layout (raw/, wiki/, SKILL.md, identity.md, config.toml) plus a row in
the ``workspaces`` SQLite table that mirrors the directory's metadata.

The filesystem is the source of truth (per invariant #11). The SQLite row is
a materialized view that ``alexandria reindex`` can rebuild from disk.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alexandria.db.connection import connect, db_path

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
GLOBAL_SLUG = "global"

DEFAULT_SKILL = """\
# SKILL.md — workspace contract

You are connected to LLM Wiki workspace **{name}**. You maintain `raw/` and
`wiki/`. The user reads; you write. Every factual claim on a wiki page must
cite a source via footnote with a verbatim quote anchor.

## The three operations
- ingest — compile a source into the wiki
- query — answer from the wiki, never from your training knowledge first
- lint — find and fix wiki rot

## Layout
- `raw/` — immutable source material
- `wiki/overview.md` — hub page (mandatory, always updated on ingest)
- `wiki/index.md` — table of contents (mandatory)
- `wiki/log.md` — append-only operation log (mandatory)
- `wiki/<topic>/<concept|entity>.md` — one topic level only
"""

DEFAULT_IDENTITY = """\
# Workspace identity

**Name:** {name}
**Slug:** {slug}
**Description:** {description}
**Created:** {created}
"""


class WorkspaceError(Exception):
    """Base class for workspace-related errors."""


class WorkspaceExistsError(WorkspaceError):
    """Raised when creating a workspace whose slug is already taken."""


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when looking up a workspace that does not exist."""


class InvalidSlugError(WorkspaceError):
    """Raised when a slug fails validation."""


@dataclass(frozen=True)
class Workspace:
    """An on-disk workspace + its database mirror row."""

    slug: str
    name: str
    description: str | None
    path: Path
    contract_version: str
    created_at: str
    updated_at: str

    @property
    def raw_dir(self) -> Path:
        return self.path / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.path / "wiki"

    @property
    def skill_path(self) -> Path:
        return self.path / "SKILL.md"

    @property
    def identity_path(self) -> Path:
        return self.path / "identity.md"

    @property
    def config_path(self) -> Path:
        return self.path / "config.toml"


# -- public API --------------------------------------------------------------


def workspaces_dir(home: Path) -> Path:
    """Return the directory that holds all workspaces under a given home."""
    return home / "workspaces"


def trash_dir(home: Path) -> Path:
    """Return the soft-delete trash directory."""
    return home / ".trash"


def validate_slug(slug: str) -> None:
    """Raise ``InvalidSlugError`` when a slug is not safe for a directory name."""
    if not SLUG_RE.match(slug):
        raise InvalidSlugError(
            f"slug {slug!r} must match {SLUG_RE.pattern} "
            "(lowercase letters, digits, '-', '_'; ≤ 63 chars; no leading hyphen)"
        )


def init_workspace(
    home: Path,
    slug: str,
    name: str,
    description: str | None = None,
) -> Workspace:
    """Create a workspace on disk and register it in SQLite.

    Idempotent: if the workspace already exists, raises ``WorkspaceExistsError``.
    Use ``get_workspace`` to look up an existing workspace.
    """
    validate_slug(slug)
    ws_path = workspaces_dir(home) / slug
    if ws_path.exists():
        raise WorkspaceExistsError(f"workspace {slug!r} already exists at {ws_path}")

    now = datetime.now(UTC).isoformat()
    ws_path.mkdir(parents=True)
    (ws_path / "raw").mkdir()
    (ws_path / "wiki").mkdir()
    (ws_path / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    (ws_path / "wiki" / ".gitkeep").write_text("", encoding="utf-8")

    skill = DEFAULT_SKILL.format(name=name)
    identity = DEFAULT_IDENTITY.format(
        name=name,
        slug=slug,
        description=description or "",
        created=now,
    )
    (ws_path / "SKILL.md").write_text(skill, encoding="utf-8")
    (ws_path / "identity.md").write_text(identity, encoding="utf-8")

    ws_config = (
        f"[workspace]\n"
        f'slug = "{slug}"\n'
        f'name = "{name}"\n'
        f'description = "{description or ""}"\n'
        f'contract_version = "v1"\n'
        f'created_at = "{now}"\n'
    )
    (ws_path / "config.toml").write_text(ws_config, encoding="utf-8")

    workspace = Workspace(
        slug=slug,
        name=name,
        description=description,
        path=ws_path,
        contract_version="v1",
        created_at=now,
        updated_at=now,
    )
    _insert_workspace_row(home, workspace)
    return workspace


def get_workspace(home: Path, slug: str) -> Workspace:
    """Look up a workspace by slug. Raises ``WorkspaceNotFoundError`` if missing."""
    validate_slug(slug)
    ws_path = workspaces_dir(home) / slug
    if not ws_path.exists():
        raise WorkspaceNotFoundError(f"workspace {slug!r} not found at {ws_path}")
    with connect(db_path(home)) as conn:
        cur = conn.execute(
            "SELECT slug, name, description, path, contract_version, created_at, updated_at "
            "FROM workspaces WHERE slug = ?",
            (slug,),
        )
        row = cur.fetchone()
    if row is None:
        # Filesystem present but DB row missing — caller should reindex.
        raise WorkspaceNotFoundError(
            f"workspace {slug!r} exists on disk but is missing from SQLite; "
            "run `alexandria reindex` to repair"
        )
    return Workspace(
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        path=Path(row["path"]),
        contract_version=row["contract_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def list_workspaces(home: Path) -> list[Workspace]:
    """Return every registered workspace, sorted by slug."""
    if not db_path(home).exists():
        return []
    with connect(db_path(home)) as conn:
        cur = conn.execute(
            "SELECT slug, name, description, path, contract_version, created_at, updated_at "
            "FROM workspaces ORDER BY slug"
        )
        rows = cur.fetchall()
    return [
        Workspace(
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            path=Path(row["path"]),
            contract_version=row["contract_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def delete_workspace(home: Path, slug: str) -> Path:
    """Soft-delete a workspace: move its directory to ``.trash/<timestamp>-<slug>/``.

    Returns the destination path. The SQLite row is removed.
    """
    validate_slug(slug)
    ws_path = workspaces_dir(home) / slug
    if not ws_path.exists():
        raise WorkspaceNotFoundError(f"workspace {slug!r} not found at {ws_path}")
    if slug == GLOBAL_SLUG:
        raise WorkspaceError("the 'global' workspace cannot be deleted")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trash = trash_dir(home)
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"{timestamp}-{slug}"
    shutil.move(str(ws_path), str(target))
    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM workspaces WHERE slug = ?", (slug,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return target


def rename_workspace(home: Path, old_slug: str, new_slug: str) -> Workspace:
    """Rename a workspace's slug. Both directory and SQLite row are updated."""
    validate_slug(old_slug)
    validate_slug(new_slug)
    if old_slug == new_slug:
        return get_workspace(home, old_slug)
    old_path = workspaces_dir(home) / old_slug
    new_path = workspaces_dir(home) / new_slug
    if not old_path.exists():
        raise WorkspaceNotFoundError(f"workspace {old_slug!r} not found")
    if new_path.exists():
        raise WorkspaceExistsError(f"workspace {new_slug!r} already exists")
    if old_slug == GLOBAL_SLUG:
        raise WorkspaceError("the 'global' workspace cannot be renamed")

    shutil.move(str(old_path), str(new_path))
    now = datetime.now(UTC).isoformat()
    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE workspaces SET slug = ?, path = ?, updated_at = ? WHERE slug = ?",
                (new_slug, str(new_path), now, old_slug),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return get_workspace(home, new_slug)


# -- internals ---------------------------------------------------------------


def _insert_workspace_row(home: Path, workspace: Workspace) -> None:
    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO workspaces
                  (slug, name, description, path, contract_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.slug,
                    workspace.name,
                    workspace.description,
                    str(workspace.path),
                    workspace.contract_version,
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
