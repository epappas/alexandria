"""``llmwiki paste`` — one-shot capture from stdin into raw/local/."""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from llmwiki.config import load_config, resolve_home, resolve_workspace
from llmwiki.core.workspace import (
    Workspace,
    WorkspaceNotFoundError,
    get_workspace,
)
from llmwiki.db.connection import connect, db_path

console = Console()

SLUG_CHARS_RE = re.compile(r"[^a-z0-9]+")


def paste_command(
    title: Optional[str] = typer.Option(
        None,
        "--title",
        "-t",
        help="Title for the captured note. Used as the filename slug.",
    ),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Override the current workspace."
    ),
    content: Optional[str] = typer.Option(
        None,
        "--content",
        help="Inline content (otherwise stdin is read).",
    ),
) -> None:
    """Capture a one-shot note into the workspace's ``raw/local/`` directory.

    Reads content from ``--content`` if given, else from stdin. The file is
    deduped by sha256 against existing files in ``raw/local/`` — re-pasting
    identical content is a no-op.
    """
    home = resolve_home()
    config = load_config(home)
    target_slug = workspace or resolve_workspace(config)

    try:
        ws = get_workspace(home, target_slug)
    except WorkspaceNotFoundError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    body = content if content is not None else sys.stdin.read()
    if not body.strip():
        console.print("[red]error:[/red] empty content (provide --content or pipe to stdin)")
        raise typer.Exit(code=1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title or "untitled")
    local_dir = ws.raw_dir / "local"
    local_dir.mkdir(parents=True, exist_ok=True)

    body_sha = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()

    # Dedup via the documents table: if a row with the same body_hash exists
    # in this workspace, the note has already been captured. We store the
    # body_hash in the metadata JSON so it survives header changes (the
    # header includes a timestamp that varies between paste calls).
    if db_path(home).exists():
        with connect(db_path(home)) as conn:
            cur = conn.execute(
                "SELECT id, path, filename FROM documents "
                "WHERE workspace = ? AND path LIKE '/raw/local/%' "
                "AND json_extract(metadata, '$.body_hash') = ?",
                (ws.slug, body_sha),
            )
            dup = cur.fetchone()
        if dup:
            console.print(
                f"[yellow]Already captured[/yellow] as "
                f"[bold]{dup['path']}{dup['filename']}[/bold]"
            )
            return

    base_name = f"{today}-{slug}"
    target = local_dir / f"{base_name}.md"
    suffix = 1
    while target.exists():
        suffix += 1
        target = local_dir / f"{base_name}-{suffix}.md"

    header = (
        f"# {title or slug.replace('-', ' ').title()}\n"
        f"\n"
        f"> Source: paste\n"
        f"> Collected: {datetime.now(timezone.utc).isoformat()}\n"
        f"> Workspace: {ws.slug}\n"
        f"\n"
    )
    target.write_text(header + body.rstrip() + "\n", encoding="utf-8")

    _record_document(home, ws, target, body_sha)

    console.print(
        f"[green]Captured[/green] [bold]{target.relative_to(ws.path)}[/bold]"
    )


def _slugify(text: str) -> str:
    out = SLUG_CHARS_RE.sub("-", text.lower()).strip("-")
    return out[:60] or "untitled"


def _record_document(home: Path, ws: Workspace, target: Path, body_sha: str) -> None:
    """Insert a row into ``documents`` so FTS5 can find this file.

    The path stored in the table follows the architecture's virtual-filesystem
    convention (`06_data_model.md`): a leading slash, the layer prefix, and
    sub-directories — e.g. ``/raw/local/`` for files under ``raw/local/``.
    """
    rel = target.relative_to(ws.path)
    parts = rel.parts
    if len(parts) < 2:
        raise ValueError(f"document {target} is not nested under raw/ or wiki/")
    layer = parts[0]
    if layer not in ("raw", "wiki"):
        raise ValueError(f"unknown layer {layer!r} for {target}")
    dir_part = "/" + "/".join(parts[:-1]) + "/"
    filename = parts[-1]

    content = target.read_text(encoding="utf-8")
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc_id = sha[:32]
    size = target.stat().st_size
    now = datetime.now(timezone.utc).isoformat()

    with connect(db_path(home)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            import json as _json

            metadata = _json.dumps({"body_hash": body_sha})
            conn.execute(
                """
                INSERT OR REPLACE INTO documents
                  (id, workspace, layer, path, filename, title, file_type,
                   content, content_hash, size_bytes, tags, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'md', ?, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    doc_id,
                    ws.slug,
                    layer,
                    dir_part,
                    filename,
                    Path(filename).stem,
                    content,
                    sha,
                    size,
                    metadata,
                    now,
                    now,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
