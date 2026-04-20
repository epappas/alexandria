"""Source kind inference — classify documents and beliefs by origin.

Maps source paths and file types to structured categories so the
belief graph can distinguish papers from opinions, code from specs.
"""

from __future__ import annotations

from pathlib import Path

# source_kind values for beliefs
PAPER = "paper"
CODE = "code"
CONVERSATION = "conversation"
SPEC = "spec"
MANUAL = "manual"
WEB = "web"
UNKNOWN = "unknown"

# Patterns that identify source kinds
_PAPER_DOMAINS = {"arxiv.org", "openreview.net", "proceedings.", "semanticscholar.org"}
_CODE_EXTENSIONS = {".py", ".ts", ".js", ".rs", ".go", ".tf", ".yml", ".yaml"}


def infer_source_kind(source_path: Path, raw_rel: str = "") -> str:
    """Infer source_kind from the source file path."""
    path_str = str(source_path).lower()
    rel = raw_rel.lower()

    # Conversations
    if "conversations/" in path_str or "conversations/" in rel:
        return CONVERSATION

    # Papers (arxiv, openreview URLs saved to raw/web/)
    if any(domain in path_str for domain in _PAPER_DOMAINS):
        return PAPER
    if any(domain in rel for domain in _PAPER_DOMAINS):
        return PAPER

    # Code files
    if source_path.suffix.lower() in _CODE_EXTENSIONS:
        return CODE

    # PDF sources are likely papers
    if source_path.suffix.lower() == ".pdf":
        return PAPER

    # Web sources
    if "raw/web/" in path_str or "raw/web/" in rel:
        return WEB

    # Markdown/text — could be manual or spec
    if source_path.suffix.lower() in (".md", ".txt", ".rst"):
        return MANUAL

    return UNKNOWN


def is_ai_authored(source_path: Path, raw_rel: str = "") -> bool:
    """Determine if a document was authored by AI (conversation capture)."""
    return infer_source_kind(source_path, raw_rel) == CONVERSATION
