"""Cascade stage operations.

Per ``15_cascade_and_convergence.md``, these four operations write into the
staged/ directory of a run, never directly into wiki/. The convergence policy
is enforced here: contradictions MUST use the hedge shape, never silently
overwrite.

All operations are pure filesystem functions — no LLM calls, no SQLite writes.
They operate on the run's ``staged/`` directory.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path


class CascadeError(Exception):
    """Raised on cascade operation failures."""


# ---------------------------------------------------------------------------
# str_replace — the surgical exactly-one-match primitive
# ---------------------------------------------------------------------------


def str_replace_staged(
    staged_file: Path,
    old_text: str,
    new_text: str,
) -> None:
    """Replace exactly one occurrence of ``old_text`` with ``new_text`` in a
    staged file. Raises ``CascadeError`` if zero or multiple matches found.

    Per ``04_guardian_agent.md``: exactly-one-match or fail. This is the
    building block that all stage operations use internally.
    """
    if not staged_file.exists():
        raise CascadeError(f"staged file not found: {staged_file}")

    content = staged_file.read_text(encoding="utf-8")
    count = content.count(old_text)

    if count == 0:
        raise CascadeError(
            f"no match for old_text in {staged_file.name} "
            f"(looking for {len(old_text)} chars starting with "
            f"{old_text[:60]!r}...)"
        )
    if count > 1:
        raise CascadeError(
            f"ambiguous: {count} matches for old_text in {staged_file.name} "
            f"— provide more surrounding context to match exactly once"
        )

    new_content = content.replace(old_text, new_text, 1)
    staged_file.write_text(new_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# The four stage operations from 15_cascade_and_convergence.md
# ---------------------------------------------------------------------------


def stage_merge(
    staged_dir: Path,
    workspace_path: Path,
    page_rel_path: str,
    section_heading: str,
    new_content: str,
    footnote_line: str,
) -> Path:
    """Merge new content into an existing section of a staged wiki page.

    The page is first copied from the live wiki to the staging directory
    (if not already staged), then the new content is appended to the named
    section. This is the **elaboration** case — the new source supports or
    extends an existing claim.

    Returns the path to the staged file.
    """
    staged_file = _ensure_staged(staged_dir, workspace_path, page_rel_path)

    content = staged_file.read_text(encoding="utf-8")

    # Find the section and append the new content
    section_marker = f"## {section_heading}"
    if section_marker not in content:
        section_marker = f"### {section_heading}"
    if section_marker not in content:
        # Section not found — append at the end before any footnotes
        footnote_section = _find_footnote_section(content)
        if footnote_section >= 0:
            content = (
                content[:footnote_section]
                + f"\n## {section_heading}\n\n{new_content}\n\n"
                + content[footnote_section:]
            )
        else:
            content += f"\n\n## {section_heading}\n\n{new_content}\n"
    else:
        # Find the end of this section (next heading or end of file)
        idx = content.index(section_marker)
        next_heading = _find_next_heading(content, idx + len(section_marker))
        if next_heading >= 0:
            content = (
                content[:next_heading]
                + f"\n{new_content}\n\n"
                + content[next_heading:]
            )
        else:
            footnote_section = _find_footnote_section(content)
            if footnote_section >= 0:
                content = (
                    content[:footnote_section]
                    + f"\n{new_content}\n\n"
                    + content[footnote_section:]
                )
            else:
                content += f"\n\n{new_content}\n"

    # Append footnote if not already present
    if footnote_line and footnote_line.strip() not in content:
        content = content.rstrip() + f"\n{footnote_line}\n"

    staged_file.write_text(content, encoding="utf-8")
    return staged_file


def stage_hedge(
    staged_dir: Path,
    workspace_path: Path,
    page_rel_path: str,
    section_heading: str,
    existing_claim_text: str,
    new_claim_text: str,
    new_source_ref: str,
    new_footnote_line: str,
    date: str | None = None,
) -> Path:
    """Wrap an existing section in a ``::: disputed`` block with dated markers.

    Per ``15_cascade_and_convergence.md``: when source N contradicts source M,
    PRESERVE the original claim and APPEND the new claim with a dated "Updated"
    marker. Never silently overwrite.

    Returns the path to the staged file.
    """
    staged_file = _ensure_staged(staged_dir, workspace_path, page_rel_path)
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")

    content = staged_file.read_text(encoding="utf-8")

    if existing_claim_text not in content:
        raise CascadeError(
            f"existing claim not found in {page_rel_path} — "
            f"cannot hedge what isn't there"
        )

    # Build the hedged block
    hedged = (
        f"::: disputed\n"
        f"{existing_claim_text}\n"
        f"\n"
        f"**Updated {date} per {new_source_ref}:** {new_claim_text}\n"
        f":::\n"
    )

    # Replace the existing claim with the hedged version
    new_content = content.replace(existing_claim_text, hedged, 1)

    # Append the new footnote
    if new_footnote_line and new_footnote_line.strip() not in new_content:
        new_content = new_content.rstrip() + f"\n{new_footnote_line}\n"

    staged_file.write_text(new_content, encoding="utf-8")
    return staged_file


def stage_new_page(
    staged_dir: Path,
    topic: str,
    slug: str,
    title: str,
    body: str,
    sources_line: str,
    raw_line: str,
    footnotes: str,
) -> Path:
    """Create a brand-new wiki page in the staging directory.

    Per the architecture, new pages are named after the concept, not the
    raw source file. The file goes under ``wiki/<topic>/<slug>.md``.
    """
    page_dir = staged_dir / topic
    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / f"{slug}.md"

    if page_path.exists():
        raise CascadeError(
            f"staged page already exists: {topic}/{slug}.md — "
            f"use stage_merge instead"
        )

    content = (
        f"# {title}\n"
        f"\n"
        f"> Sources: {sources_line}\n"
        f"> Raw: {raw_line}\n"
        f"> Updated: {datetime.now(UTC).strftime('%Y-%m-%d')}\n"
        f"\n"
        f"## Overview\n\n"
        f"{body}\n"
    )
    if footnotes:
        content += f"\n{footnotes}\n"

    page_path.write_text(content, encoding="utf-8")
    return page_path


def stage_cross_ref(
    staged_dir: Path,
    workspace_path: Path,
    from_page: str,
    to_page: str,
    label: str | None = None,
) -> Path:
    """Add a See Also cross-reference link from one page to another.

    If a ``## See Also`` section exists, the link is appended to it.
    Otherwise, one is created before the footnotes section.
    """
    staged_file = _ensure_staged(staged_dir, workspace_path, from_page)
    content = staged_file.read_text(encoding="utf-8")

    # Compute relative link
    Path(from_page).parent.parts
    Path(to_page).parts
    rel_link = _relative_link(from_page, to_page)
    link_text = label or Path(to_page).stem.replace("-", " ").title()
    link_line = f"- [{link_text}]({rel_link})"

    if link_line in content:
        return staged_file  # already present

    if "## See Also" in content:
        idx = content.index("## See Also")
        end = _find_next_heading(content, idx + len("## See Also"))
        if end >= 0:
            content = content[:end] + f"{link_line}\n" + content[end:]
        else:
            content += f"\n{link_line}\n"
    else:
        footnote_section = _find_footnote_section(content)
        if footnote_section >= 0:
            content = (
                content[:footnote_section]
                + f"\n## See Also\n\n{link_line}\n\n"
                + content[footnote_section:]
            )
        else:
            content += f"\n\n## See Also\n\n{link_line}\n"

    staged_file.write_text(content, encoding="utf-8")
    return staged_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_staged(
    staged_dir: Path,
    workspace_path: Path,
    page_rel_path: str,
) -> Path:
    """Copy a live wiki page to the staging directory if not already there."""
    staged_file = staged_dir / page_rel_path
    if staged_file.exists():
        return staged_file

    live_file = workspace_path / "wiki" / page_rel_path
    if not live_file.exists():
        raise CascadeError(f"wiki page not found: wiki/{page_rel_path}")

    staged_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(live_file), str(staged_file))
    return staged_file


def _find_footnote_section(content: str) -> int:
    """Find the byte offset where footnotes begin (first ``[^N]:`` line)."""
    import re

    match = re.search(r"^\[\^\d+\]:", content, re.MULTILINE)
    return match.start() if match else -1


def _find_next_heading(content: str, after: int) -> int:
    """Find the next markdown heading (##) after ``after``."""
    import re

    match = re.search(r"^#{1,3} ", content[after:], re.MULTILINE)
    return after + match.start() if match else -1


def _relative_link(from_page: str, to_page: str) -> str:
    """Compute a relative path from one wiki page to another."""
    from_dir = Path(from_page).parent
    to_path = Path(to_page)
    try:
        rel = to_path.relative_to(from_dir)
        return str(rel)
    except ValueError:
        # Different directories — go up then down
        from_parts = from_dir.parts
        to_parts = to_path.parts
        common = 0
        for a, b in zip(from_parts, to_parts, strict=False):
            if a != b:
                break
            common += 1
        ups = len(from_parts) - common
        return "/".join([".."] * ups + list(to_parts[common:]))
