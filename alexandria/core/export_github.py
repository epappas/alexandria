"""GitHub-friendly three-layer export.

Produces a vault layout optimized for browsing on GitHub:

* ``.alexandria/`` — canonical backup of raw/ and wiki/ in alexandria's
  native layout; suitable for disaster recovery via reindex.
* ``wiki/`` — human-readable projection with title-slug filenames,
  per-folder READMEs, and resolved raw links.
* ``journal/`` — reverse-chronological activity log, one file per month,
  cross-linked to wiki pages and raw sources.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GithubExportResult:
    """Summary of a GitHub-format export."""

    files_exported: int
    topics: int
    journal_months: int
    output_path: Path


def export_github(
    workspace_path: Path,
    output_dir: Path,
    conn: sqlite3.Connection,
    workspace: str,
) -> GithubExportResult:
    """Run the full three-layer export."""
    output_dir.mkdir(parents=True, exist_ok=True)

    _reset_tree(output_dir / ".alexandria")
    _reset_tree(output_dir / "wiki")
    _reset_tree(output_dir / "journal")

    _copy_canonical(workspace_path, output_dir / ".alexandria")

    pages = _collect_pages(workspace_path / "wiki")
    slug_map = _assign_slugs(pages)
    _write_human_wiki(pages, slug_map, output_dir / "wiki")

    months = _write_journal(output_dir / "journal", conn, workspace, slug_map)

    _write_root_readme(output_dir, pages, months)

    return GithubExportResult(
        files_exported=len(pages),
        topics=len({p["topic"] for p in pages}),
        journal_months=months,
        output_path=output_dir,
    )


# --- Canonical backup -------------------------------------------------------


def _copy_canonical(workspace_path: Path, dest: Path) -> None:
    """Copy raw/ and wiki/ as the backup layer.

    Strips nested ``.git`` directories from git-adapter clones so the outer
    repo records actual files rather than opaque gitlinks (mode 160000).
    """
    def _ignore(_src: str, names: list[str]) -> list[str]:
        return [n for n in names if n == ".git"]

    for sub in ("raw", "wiki"):
        src = workspace_path / sub
        if src.exists():
            shutil.copytree(
                str(src), str(dest / sub),
                dirs_exist_ok=False, ignore=_ignore,
            )


# --- Wiki projection --------------------------------------------------------


def _collect_pages(wiki_dir: Path) -> list[dict[str, Any]]:
    """Read every wiki page and gather title, topic, body."""
    if not wiki_dir.exists():
        return []
    pages: list[dict[str, Any]] = []
    for src in sorted(wiki_dir.rglob("*.md")):
        if src.name in ("log.md", "index.md"):
            continue
        content = src.read_text(encoding="utf-8")
        rel = src.relative_to(wiki_dir)
        topic = rel.parts[0] if len(rel.parts) > 1 else "general"
        title = _extract_title(content) or src.stem.replace("-", " ").title()
        pages.append({
            "src": src,
            "rel": rel,
            "original_name": src.stem,
            "topic": topic,
            "title": title,
            "content": content,
            "preview": _extract_preview(content),
            "mtime": src.stat().st_mtime,
        })
    return pages


def _assign_slugs(pages: list[dict[str, Any]]) -> dict[str, str]:
    """Pick title-based filenames with collision handling."""
    slugs: dict[str, str] = {}
    used_per_topic: dict[str, set[str]] = defaultdict(set)
    for p in pages:
        base = _title_to_slug(p["title"])
        candidate = base
        i = 2
        while candidate in used_per_topic[p["topic"]]:
            candidate = f"{base}-{i}"
            i += 1
        used_per_topic[p["topic"]].add(candidate)
        slugs[str(p["rel"])] = candidate
        p["new_slug"] = candidate
    return slugs


def _write_human_wiki(
    pages: list[dict[str, Any]],
    slug_map: dict[str, str],
    wiki_root: Path,
) -> None:
    """Write title-named page files + per-topic READMEs."""
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pages:
        by_topic[p["topic"]].append(p)

    for topic, topic_pages in by_topic.items():
        topic_dir = wiki_root / topic
        topic_dir.mkdir(parents=True, exist_ok=True)
        for p in topic_pages:
            dest = topic_dir / f"{p['new_slug']}.md"
            body = _rewrite_page(p["content"], pages, slug_map, p["topic"])
            dest.write_text(body, encoding="utf-8")

        _write_topic_readme(topic_dir, topic, topic_pages)

    _write_wiki_readme(wiki_root, by_topic)


def _rewrite_page(
    content: str,
    pages: list[dict[str, Any]],
    slug_map: dict[str, str],
    current_topic: str,
) -> str:
    """Resolve inter-wiki links + raw links to the new layout."""
    old_to_new: dict[str, tuple[str, str]] = {}
    for p in pages:
        old_to_new[p["original_name"]] = (p["topic"], p["new_slug"])

    def _link_sub(match: re.Match[str]) -> str:
        label = match.group(1)
        path = match.group(2)
        stem = Path(path).stem
        if stem in old_to_new:
            topic, slug = old_to_new[stem]
            if topic == current_topic:
                return f"[{label}]({slug}.md)"
            return f"[{label}](../{topic}/{slug}.md)"
        return match.group(0)

    # rewrite internal wiki cross-links
    content = re.sub(r"\[([^\]]+)\]\(([^)]+\.md)\)", _link_sub, content)

    # rewrite raw/ footnote references to the canonical backup
    content = re.sub(
        r"(\[\^\d+\]:\s*)(raw/[^\s)]+)",
        r"\1../../.alexandria/\2",
        content,
    )
    content = re.sub(
        r"\]\(\.\./\.\./raw/",
        "](../../.alexandria/raw/",
        content,
    )

    # collapse trailing consecutive duplicate footnote lines
    content = _dedupe_footnotes(content)
    return content


def _dedupe_footnotes(content: str) -> str:
    """Remove consecutive identical footnote definitions."""
    lines = content.split("\n")
    out: list[str] = []
    prev_fn: str | None = None
    for line in lines:
        if re.match(r"^\[\^\d+\]:\s*", line):
            if line == prev_fn:
                continue
            prev_fn = line
        else:
            prev_fn = None
        out.append(line)
    return "\n".join(out)


def _write_topic_readme(
    topic_dir: Path,
    topic: str,
    topic_pages: list[dict[str, Any]],
) -> None:
    """Write README.md for a topic folder."""
    lines = [f"# {topic.replace('-', ' ').title()}", ""]
    lines.append(f"{len(topic_pages)} page(s) in this topic.")
    lines.append("")
    for p in sorted(topic_pages, key=lambda x: x["title"].lower()):
        lines.append(f"## [{p['title']}]({p['new_slug']}.md)")
        if p["preview"]:
            lines.append("")
            lines.append(p["preview"])
        lines.append("")
    (topic_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_wiki_readme(
    wiki_root: Path,
    by_topic: dict[str, list[dict[str, Any]]],
) -> None:
    """Write the wiki-root README listing topics."""
    lines = ["# Wiki", ""]
    lines.append(f"{sum(len(v) for v in by_topic.values())} pages across "
                 f"{len(by_topic)} topics.")
    lines.append("")
    for topic in sorted(by_topic.keys()):
        pages = by_topic[topic]
        lines.append(f"## [{topic.replace('-', ' ').title()}]"
                     f"({topic}/README.md) ({len(pages)})")
        lines.append("")
        for p in sorted(pages, key=lambda x: x["title"].lower())[:5]:
            lines.append(f"- [{p['title']}]({topic}/{p['new_slug']}.md)")
        if len(pages) > 5:
            lines.append(f"- … [see all {len(pages)} →]({topic}/README.md)")
        lines.append("")
    wiki_root.mkdir(parents=True, exist_ok=True)
    (wiki_root / "README.md").write_text("\n".join(lines), encoding="utf-8")


# --- Journal ----------------------------------------------------------------


def _write_journal(
    journal_root: Path,
    conn: sqlite3.Connection,
    workspace: str,
    slug_map: dict[str, str],
) -> int:
    """Write monthly journal files with cross-links."""
    rows = conn.execute(
        """
        SELECT path, title, created_at
          FROM documents
         WHERE workspace = ? AND layer = 'wiki'
           AND path NOT LIKE '%log.md' AND path NOT LIKE '%index.md'
         ORDER BY created_at DESC
        """,
        (workspace,),
    ).fetchall()

    raw_by_title = _index_raw_by_title(conn, workspace)
    belief_counts = _belief_counts_by_path(conn, workspace)

    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        path = row["path"]
        created = row["created_at"]
        month = created[:7] if created else "unknown"
        wiki_rel = _wiki_path_for(path, slug_map)
        raw_rel = raw_by_title.get(row["title"])
        by_month[month].append({
            "created_at": created,
            "title": row["title"],
            "wiki_rel": wiki_rel,
            "raw_rel": raw_rel,
            "beliefs": belief_counts.get(path, 0),
        })

    journal_root.mkdir(parents=True, exist_ok=True)
    for month, entries in by_month.items():
        _write_month_file(journal_root, month, entries)
    _write_journal_readme(journal_root, by_month)
    return len(by_month)


def _index_raw_by_title(conn: sqlite3.Connection, workspace: str) -> dict[str, str]:
    """Map title -> raw/... path for quick journal linking."""
    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT path, title FROM documents WHERE workspace = ? AND layer = 'raw'",
        (workspace,),
    ):
        if row["title"] and row["title"] not in out:
            out[row["title"]] = row["path"]
    return out


def _belief_counts_by_path(
    conn: sqlite3.Connection, workspace: str,
) -> dict[str, int]:
    """Count active beliefs per wiki_document_path."""
    counts: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT wiki_document_path, COUNT(*) AS n
          FROM wiki_beliefs
         WHERE workspace = ? AND superseded_at IS NULL
         GROUP BY wiki_document_path
        """,
        (workspace,),
    ):
        counts[row["wiki_document_path"]] = row["n"]
    return counts


def _write_month_file(
    journal_root: Path, month: str, entries: list[dict[str, Any]],
) -> None:
    """Write one month's entries to journal/YYYY-MM.md."""
    lines = [f"# Journal — {month}", ""]
    lines.append(f"{len(entries)} ingest(s) this month.")
    lines.append("")
    for e in entries:
        ts = (e["created_at"] or "")[:16].replace("T", " ")
        lines.append(f"## {ts} — {e['title']}")
        lines.append("")
        if e["wiki_rel"]:
            lines.append(f"- Wiki: [{e['title']}](../wiki/{e['wiki_rel']})")
        if e["raw_rel"]:
            lines.append(f"- Raw: [{Path(e['raw_rel']).name}]"
                         f"(../.alexandria/{e['raw_rel']})")
        if e["beliefs"]:
            lines.append(f"- Beliefs: {e['beliefs']} active")
        lines.append("")
    (journal_root / f"{month}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_journal_readme(
    journal_root: Path, by_month: dict[str, list[dict[str, Any]]],
) -> None:
    """Index all monthly files."""
    lines = ["# Journal", ""]
    total = sum(len(v) for v in by_month.values())
    lines.append(f"{total} ingest(s) across {len(by_month)} month(s).")
    lines.append("")
    for month in sorted(by_month.keys(), reverse=True):
        lines.append(f"- [{month}]({month}.md) — {len(by_month[month])} entries")
    (journal_root / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _wiki_path_for(raw_path: str, slug_map: dict[str, str]) -> str | None:
    """Translate wiki/foo/bar.md -> topic/new-slug.md in the human layer."""
    if not raw_path.startswith("wiki/"):
        return None
    rel = raw_path[len("wiki/"):]
    new_slug = slug_map.get(rel)
    if not new_slug:
        return None
    parts = Path(rel).parts
    topic = parts[0] if len(parts) > 1 else "general"
    return f"{topic}/{new_slug}.md"


# --- Root README ------------------------------------------------------------


def _write_root_readme(
    output_dir: Path, pages: list[dict[str, Any]], journal_months: int,
) -> None:
    """Top-level landing page that orients the reader."""
    topics = len({p["topic"] for p in pages})
    lines = [
        "# Alexandria knowledge vault",
        "",
        "This repository is a GitHub-friendly mirror of an alexandria "
        "knowledge base.",
        "",
        f"- **{len(pages)} wiki pages** across **{topics} topics**",
        f"- **{journal_months} months** of activity in `journal/`",
        "",
        "## Layout",
        "",
        "- [`wiki/`](wiki/README.md) — human-readable projection with "
        "title-slug filenames and per-topic indexes.",
        "- [`journal/`](journal/README.md) — chronological activity log with "
        "links to wiki pages and raw sources.",
        "- `.alexandria/` — canonical backup of the native alexandria layout "
        "(raw + wiki). Use this to rehydrate the knowledge base on a fresh "
        "machine via `alxia reindex --rebuild-beliefs`.",
        "- `inbox.md` — write surface for mobile; append URLs to be ingested "
        "by the desktop sync job.",
        "- `inbox-archive.md` — history of ingested inbox entries.",
        "",
        "## Regeneration",
        "",
        "The `wiki/`, `journal/`, and `.alexandria/` trees are fully "
        "regenerated on every sync — do not hand-edit pages in those trees. "
        "The only hand-writable files are `inbox.md` (next capture) and "
        "`inbox-archive.md` (history).",
    ]
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


# --- Helpers ----------------------------------------------------------------


def _reset_tree(path: Path) -> None:
    """Remove a directory so re-exports don't leave stale files."""
    if path.exists():
        shutil.rmtree(str(path))


def _extract_title(content: str) -> str | None:
    """Pull title from the first H1 line."""
    for line in content.split("\n")[:5]:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_preview(content: str) -> str:
    """Return the first non-empty paragraph after the H1, trimmed."""
    lines = content.split("\n")
    saw_h1 = False
    para: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not saw_h1:
            if stripped.startswith("# "):
                saw_h1 = True
            continue
        if stripped.startswith(">") or stripped.startswith("#"):
            continue
        if not stripped:
            if para:
                break
            continue
        para.append(stripped)
        if sum(len(p) for p in para) > 240:
            break
    out = " ".join(para).strip()
    return out[:240] + ("…" if len(out) > 240 else "")


def _title_to_slug(title: str) -> str:
    """Convert a page title to a short filesystem-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")
    return slug or "untitled"
