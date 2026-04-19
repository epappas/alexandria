"""Export wiki content to Obsidian, Markdown, or JSON bundle."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExportResult:
    """Summary of an export operation."""

    format: str
    files_exported: int
    output_path: Path


def export_markdown(workspace_path: Path, output_dir: Path) -> ExportResult:
    """Copy wiki/ tree to output with an index page."""
    wiki_dir = workspace_path / "wiki"
    if not wiki_dir.exists():
        return ExportResult(format="markdown", files_exported=0, output_path=output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    index_lines = ["# Wiki Index\n"]

    for src in sorted(wiki_dir.rglob("*.md")):
        rel = src.relative_to(wiki_dir)
        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        index_lines.append(f"- [{rel.stem}]({rel})")
        count += 1

    (output_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")
    return ExportResult(format="markdown", files_exported=count, output_path=output_dir)


def export_obsidian(
    workspace_path: Path, output_dir: Path, conn: sqlite3.Connection, workspace: str,
) -> ExportResult:
    """Copy wiki/ with YAML frontmatter and Map of Content."""
    wiki_dir = workspace_path / "wiki"
    if not wiki_dir.exists():
        return ExportResult(format="obsidian", files_exported=0, output_path=output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    topics: dict[str, list[str]] = {}

    for src in sorted(wiki_dir.rglob("*.md")):
        rel = src.relative_to(wiki_dir)
        content = src.read_text(encoding="utf-8")
        title = _extract_title(content) or rel.stem

        # Build frontmatter
        topic = rel.parts[0] if len(rel.parts) > 1 else "root"
        aliases = [rel.stem.replace("-", " ").title()]
        frontmatter = (
            f"---\ntitle: {title}\n"
            f"aliases: {json.dumps(aliases)}\n"
            f"tags: [{topic}]\n---\n\n"
        )

        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(frontmatter + content, encoding="utf-8")

        topics.setdefault(topic, []).append(f"- [[{rel.stem}]]")
        count += 1

    # Generate Map of Content
    moc_lines = ["# Map of Content\n"]
    for topic, pages in sorted(topics.items()):
        moc_lines.append(f"\n## {topic}\n")
        moc_lines.extend(pages)
    (output_dir / "MOC.md").write_text("\n".join(moc_lines), encoding="utf-8")

    return ExportResult(format="obsidian", files_exported=count, output_path=output_dir)


def export_json(
    workspace_path: Path, output_dir: Path, conn: sqlite3.Connection, workspace: str,
) -> ExportResult:
    """Export documents + beliefs as a JSON bundle."""
    output_dir.mkdir(parents=True, exist_ok=True)

    docs = conn.execute(
        "SELECT id, path, title, layer, content_hash, size_bytes, created_at, updated_at FROM documents WHERE workspace = ?",
        (workspace,),
    ).fetchall()

    beliefs = conn.execute(
        "SELECT belief_id, statement, topic, subject, predicate, object, asserted_at, superseded_at FROM wiki_beliefs WHERE workspace = ?",
        (workspace,),
    ).fetchall()

    bundle = {
        "workspace": workspace,
        "documents": [dict(d) for d in docs],
        "beliefs": [dict(b) for b in beliefs],
        "exported_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }

    out_path = output_dir / "alexandria-export.json"
    out_path.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
    return ExportResult(format="json", files_exported=len(docs), output_path=out_path)


def _extract_title(content: str) -> str | None:
    """Extract title from first # heading."""
    for line in content.split("\n")[:5]:
        if line.startswith("# "):
            return line[2:].strip()
    return None
