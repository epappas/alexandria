"""Post-commit cross-reference discovery.

Two-pass wikilink resolution:
1. Scan changed pages for mentions of existing wiki titles
2. Scan all pages for mentions of new titles
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CrossRefCandidate:
    """A discovered cross-reference between two wiki pages."""

    from_page: str
    to_page: str
    label: str


def discover_cross_refs(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    changed_pages: list[str],
    *,
    limit: int = 20,
) -> list[CrossRefCandidate]:
    """Find cross-reference opportunities between wiki pages."""
    # Get all wiki page titles
    all_pages = conn.execute(
        "SELECT title, path FROM documents WHERE workspace = ? AND layer = 'wiki'",
        (workspace,),
    ).fetchall()
    title_to_path = {r["title"]: r["path"] for r in all_pages if r["title"]}

    candidates: list[CrossRefCandidate] = []
    seen: set[tuple[str, str]] = set()

    # Pass 1: changed pages mention existing titles
    for changed in changed_pages:
        full = workspace_path / "wiki" / changed
        if not full.exists():
            continue
        content = full.read_text(encoding="utf-8")
        changed_wiki = f"wiki/{changed}"

        for title, path in title_to_path.items():
            if path == changed_wiki or len(title) < 4:
                continue
            if _mentions_title(content, title) and not _already_linked(content, path):
                key = (changed_wiki, path)
                if key not in seen:
                    candidates.append(CrossRefCandidate(changed_wiki, path, title))
                    seen.add(key)

    # Pass 2: existing pages mention new page titles
    changed_titles = {
        title: path for title, path in title_to_path.items()
        if any(path == f"wiki/{c}" for c in changed_pages)
    }
    for title, new_path in changed_titles.items():
        if len(title) < 4:
            continue
        for other in all_pages:
            other_path = other["path"]
            if other_path == new_path:
                continue
            other_full = workspace_path / other_path
            if not other_full.exists():
                continue
            other_content = other_full.read_text(encoding="utf-8")
            if _mentions_title(other_content, title) and not _already_linked(other_content, new_path):
                key = (other_path, new_path)
                if key not in seen:
                    candidates.append(CrossRefCandidate(other_path, new_path, title))
                    seen.add(key)

    return candidates[:limit]


def _mentions_title(content: str, title: str) -> bool:
    """Check if content mentions a title (case-insensitive, word boundary)."""
    pattern = re.compile(r'\b' + re.escape(title) + r'\b', re.IGNORECASE)
    return bool(pattern.search(content))


def _already_linked(content: str, target_path: str) -> bool:
    """Check if a page already has a link or See Also to the target."""
    return target_path in content or "## See Also" in content and target_path.split("/")[-1] in content
