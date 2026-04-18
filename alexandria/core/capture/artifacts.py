"""Extract and prioritize ingestible artifacts from conversation transcripts.

Scans conversation messages for URLs, deduplicates, ranks by source
quality (arxiv > github > PDF > blog), and returns them for ingestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# URL extraction pattern
_URL_RE = re.compile(r'https?://[^\s"\\>\)\]\},]+')

# Domains to skip (navigation, docs, generic)
_SKIP_DOMAINS = frozenset({
    "docs.openreview.net", "openreview.net/api",
    "fonts.googleapis.com", "cdn.jsdelivr.net",
    "www.w3.org", "schema.org",
})

# Domain priority: higher = more valuable
_DOMAIN_PRIORITY: dict[str, int] = {
    "arxiv.org": 90,
    "openreview.net": 85,
    "proceedings.iclr.cc": 85,
    "github.com": 80,
    "huggingface.co": 75,
    "research.google": 70,
    "ai.meta.com": 70,
    "developer.nvidia.com": 65,
    "semanticscholar.org": 60,
    "researchgate.net": 55,
}
_DEFAULT_PRIORITY = 30


@dataclass
class Artifact:
    """A discovered artifact from a conversation."""

    url: str
    kind: str  # "paper", "repo", "pdf", "page"
    priority: int
    domain: str


def extract_artifacts(messages: list[dict[str, str]]) -> list[Artifact]:
    """Extract and rank artifacts from conversation messages."""
    seen: set[str] = set()
    artifacts: list[Artifact] = []

    for msg in messages:
        content = msg.get("content", "")
        for raw_url in _URL_RE.findall(content):
            url = _clean_url(raw_url)
            if not url or url in seen:
                continue
            seen.add(url)

            parsed = urlparse(url)
            domain = parsed.hostname or ""

            if _should_skip(domain, parsed.path):
                continue

            kind = _classify(domain, parsed.path, url)
            priority = _score(domain, parsed.path, kind)
            artifacts.append(Artifact(url=url, kind=kind, priority=priority, domain=domain))

    artifacts.sort(key=lambda a: a.priority, reverse=True)
    return artifacts


def _clean_url(raw: str) -> str | None:
    """Clean a raw URL extracted from text."""
    # Strip trailing punctuation and escape sequences
    url = raw.rstrip(".,;:!?)}]'\"")
    url = url.split("\\")[0]  # strip \n, \t etc
    url = url.split("\n")[0]
    if len(url) < 20:
        return None
    # Normalize arxiv: prefer /abs/ over /html/ or /pdf/
    if "arxiv.org/html/" in url:
        url = url.replace("/html/", "/abs/").split("v")[0]
    if "arxiv.org/pdf/" in url:
        url = url.replace("/pdf/", "/abs/")
    return url


def _should_skip(domain: str, path: str) -> bool:
    """Filter out navigation/docs/noise URLs."""
    if domain in _SKIP_DOMAINS:
        return True
    # Skip fragment-only or anchor links
    if not domain:
        return True
    # Skip API/docs paths
    if "/api/" in path or "/docs/" in path:
        return True
    return False


def _classify(domain: str, path: str, url: str) -> str:
    """Classify the artifact type."""
    if "arxiv.org" in domain:
        return "paper"
    if "openreview.net" in domain and ("/pdf" in path or "/forum" in path):
        return "paper"
    if "proceedings" in domain and ".pdf" in path:
        return "paper"
    if "github.com" in domain:
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) == 2:
            return "repo"
        return "page"
    if "huggingface.co" in domain and "/papers/" in path:
        return "paper"
    if url.endswith(".pdf"):
        return "pdf"
    return "page"


def _score(domain: str, path: str, kind: str) -> int:
    """Score the artifact for prioritization."""
    base = _DEFAULT_PRIORITY
    for pattern, priority in _DOMAIN_PRIORITY.items():
        if pattern in domain:
            base = priority
            break
    # Boost papers and repos
    if kind == "paper":
        base += 5
    elif kind == "repo":
        base += 3
    return base
