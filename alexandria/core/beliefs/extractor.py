"""Extract beliefs from a wiki page.

Parses a wiki page's markdown to identify substantive claims, link them
to their footnote citations, and produce structured Belief objects.

Per ``19_belief_revision.md``: beliefs are extracted at write time by the
writer, not by a separate background process. Each belief corresponds to
an actual claim in the wiki page text with a footnote citation.
"""

from __future__ import annotations

import re
from pathlib import Path

from alexandria.core.beliefs.model import Belief
from alexandria.core.citations import extract_footnotes

# Section heading pattern
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# Footnote reference in body text: [^N]
FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")


def extract_beliefs_from_page(
    page_content: str,
    page_path: str,
    workspace: str,
    topic: str,
    run_id: str | None = None,
) -> list[Belief]:
    """Extract structured beliefs from a wiki page.

    Each belief is a paragraph or sentence that contains at least one
    footnote reference ``[^N]``. The statement is the text around the
    reference, and the footnote_ids link to the citation definitions.
    """
    footnotes = extract_footnotes(page_content)
    footnote_map = {fn.footnote_id: fn for fn in footnotes}

    beliefs: list[Belief] = []
    current_section = ""
    lines = page_content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        heading_match = HEADING_RE.match(line)
        if heading_match:
            current_section = heading_match.group(2).strip()
            i += 1
            continue

        refs = FOOTNOTE_REF_RE.findall(line)
        if refs and not line.startswith("[^"):
            statement = _clean_statement(line)
            if len(statement) >= 10:
                fn_ids = list(set(refs))
                belief = Belief(
                    workspace=workspace,
                    statement=statement[:500],
                    topic=topic,
                    wiki_document_path=page_path,
                    wiki_section_anchor=_slugify_heading(current_section) if current_section else None,
                    footnote_ids=fn_ids,
                    asserted_in_run=run_id,
                )

                _try_extract_structured(belief, statement, footnote_map, fn_ids)
                beliefs.append(belief)

        i += 1

    return beliefs


def _clean_statement(line: str) -> str:
    """Clean a line to produce a readable belief statement."""
    cleaned = line.strip()
    cleaned = FOOTNOTE_REF_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _slugify_heading(heading: str) -> str:
    """Convert a heading to a markdown anchor slug."""
    slug = heading.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug


def _try_extract_structured(
    belief: Belief,
    statement: str,
    footnote_map: dict,
    fn_ids: list[str],
) -> None:
    """Best-effort extraction of subject/predicate/object from the statement.

    This is optional per ``19_belief_revision.md`` — the structured fields
    are encouraged but not required. We use simple heuristics:
    - Subject: first noun phrase (before "is", "uses", "has", etc.)
    - Predicate: the verb phrase
    - Object: everything after the verb
    """
    patterns = [
        (r"^(.+?)\s+(uses?|is|are|has|have)\s+(.+)$", "is"),
        (r"^(.+?)\s+(was|were|moved to|depends on|relies on)\s+(.+)$", None),
        (r"^(.+?)\s+(at|in|on|for)\s+(.+)$", None),
    ]

    lower = statement.lower()
    for pattern, default_pred in patterns:
        match = re.match(pattern, lower)
        if match:
            belief.subject = match.group(1).strip()[:100]
            belief.predicate = match.group(2).strip()
            belief.object = match.group(3).strip()[:200]
            return
