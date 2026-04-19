"""Extract footnote citations from a wiki page's markdown.

Parses ``[^N]: source_file, p.X — "verbatim quote"`` into structured
``Footnote`` objects with the quote span for hash-anchor verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Matches: [^1]: filename.md, p.3 — "verbatim quote text"
# Also:    [^1]: filename.md — "verbatim quote text"
# Also:    [^1]: filename.md, p.3
FOOTNOTE_RE = re.compile(
    r'^\[\^(\d+)\]:\s*'              # [^N]:
    r'([^\s,—]+)'                     # filename (no spaces, commas, or em-dashes)
    r'(?:,\s*p\.?\s*(\d+))?'         # optional , p.N
    r'(?:\s*(?:—|--)\s*'             # optional — or --
    r'"([^"]+)")?'                    # optional "verbatim quote"
    r'\s*$',
    re.MULTILINE,
)


@dataclass(frozen=True)
class Footnote:
    """A parsed footnote citation from a wiki page."""

    footnote_id: str
    source_file: str
    page_hint: int | None
    quote: str | None
    raw_line: str

    @property
    def has_quote(self) -> bool:
        return self.quote is not None and len(self.quote.strip()) > 0


def extract_footnotes(text: str) -> list[Footnote]:
    """Parse all ``[^N]: ...`` footnotes from a wiki page."""
    results: list[Footnote] = []
    for match in FOOTNOTE_RE.finditer(text):
        fn = Footnote(
            footnote_id=match.group(1),
            source_file=match.group(2),
            page_hint=int(match.group(3)) if match.group(3) else None,
            quote=match.group(4),
            raw_line=match.group(0),
        )
        results.append(fn)
    return results
