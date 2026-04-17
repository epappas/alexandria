"""Web page fetching and conversion to markdown.

Fetches a URL, extracts readable content, and converts to markdown.
Supports HTML pages and direct PDF URLs.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class WebFetchError(Exception):
    pass


def fetch_url(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch a URL and return extracted content.

    Returns dict with: url, title, content (markdown), content_type, content_hash.
    Handles HTML pages and PDF URLs.
    """
    _validate_url(url)

    headers = {"User-Agent": "alexandria/0.2 (knowledge engine)"}
    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
    except HTTPError as exc:
        raise WebFetchError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise WebFetchError(f"network error: {exc.reason}") from exc

    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return _handle_pdf(url, data)

    return _handle_html(url, data, content_type)


def fetch_and_save(url: str, workspace_path: Path, timeout: int = 30) -> Path:
    """Fetch a URL and save as a markdown file in raw/web/. Returns the file path."""
    result = fetch_url(url, timeout=timeout)

    web_dir = workspace_path / "raw" / "web"
    web_dir.mkdir(parents=True, exist_ok=True)

    slug = _url_to_slug(url)
    md_path = web_dir / f"{slug}.md"

    lines = [
        f"# {result['title']}",
        "",
        f"- source: {result['url']}",
        f"- fetched: {_now_iso()}",
        f"- type: {result['content_type']}",
        "", "---", "",
        result["content"],
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # If it was a PDF, also save the original binary
    if result.get("pdf_bytes"):
        pdf_path = web_dir / f"{slug}.pdf"
        pdf_path.write_bytes(result["pdf_bytes"])

    return md_path


def _handle_html(url: str, data: bytes, content_type: str) -> dict[str, Any]:
    """Extract readable content from HTML."""
    charset = _extract_charset(content_type)
    html = data.decode(charset, errors="replace")

    title = _extract_title(html)
    content = _html_to_markdown(html)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "url": url,
        "title": title,
        "content": content,
        "content_type": "html",
        "content_hash": content_hash,
    }


def _handle_pdf(url: str, data: bytes) -> dict[str, Any]:
    """Extract text from a fetched PDF."""
    try:
        import pymupdf
    except ImportError:
        raise WebFetchError(
            "pymupdf required for PDF URLs. Install: pip install alexandria-wiki[pdf]"
        )

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise WebFetchError(f"failed to parse PDF from {url}: {exc}") from exc

    metadata = doc.metadata or {}
    title = metadata.get("title", "").strip() or _title_from_url(url)

    pages: list[str] = []
    for i, page in enumerate(doc):
        text = page.get_text("text").strip()
        if text:
            pages.append(f"## Page {i + 1}\n\n{text}")
    doc.close()

    content = "\n\n".join(pages)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "url": url,
        "title": title,
        "content": content,
        "content_type": "pdf",
        "content_hash": content_hash,
        "pdf_bytes": data,
    }


def _html_to_markdown(html: str) -> str:
    """Convert HTML to readable markdown, extracting main content."""
    # Remove script/style blocks entirely
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Extract main content area if possible
    main_html = _extract_main_content(html) or html

    try:
        from markdownify import markdownify
        md = markdownify(
            main_html, heading_style="ATX",
            strip=["nav", "footer", "header", "iframe", "form",
                   "object", "embed", "aside", "select", "input", "button"],
        )
        # Clean up
        md = re.sub(r"\n{3,}", "\n\n", md)
        # Remove lines that are just links/brackets with no prose
        lines = md.split("\n")
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # Skip lines that are just navigation artifacts
            if stripped in ("", "Search", "GO", "Help", "Login", "About"):
                if not stripped:
                    cleaned.append(line)
                continue
            # Skip lines that are just a bare link or image
            if re.match(r"^\[.*\]\(.*\)$", stripped) and len(stripped) < 60:
                continue
            # Skip lines that are just "[![" image links
            if stripped.startswith("[!["):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    except ImportError:
        clean = re.sub(r"<[^>]+>", "", main_html)
        import html as html_mod
        return html_mod.unescape(clean).strip()


def _extract_main_content(html: str) -> str | None:
    """Extract the main content area from HTML, stripping nav/sidebar/footer."""
    # Try common content containers in priority order
    patterns = [
        # article tag
        (r"<article[^>]*>(.*?)</article>", re.DOTALL | re.IGNORECASE),
        # main tag
        (r"<main[^>]*>(.*?)</main>", re.DOTALL | re.IGNORECASE),
        # role=main
        (r'<[^>]+role=["\']main["\'][^>]*>(.*?)</\w+>', re.DOTALL | re.IGNORECASE),
        # id=content or id=main-content
        (r'<[^>]+id=["\'](?:content|main-content|bodyContent|mw-content-text)["\'][^>]*>(.*?)</\w+>', re.DOTALL | re.IGNORECASE),
        # class containing "content" or "article" (broad fallback)
        (r'<div[^>]+class=["\'][^"\']*(?:article-body|post-content|entry-content|paper-content)[^"\']*["\'][^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
    ]
    for pattern, flags in patterns:
        match = re.search(pattern, html, flags)
        if match and len(match.group(1).strip()) > 200:
            return match.group(1)
    return None


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        import html as html_mod
        return html_mod.unescape(match.group(1)).strip()
    return "Untitled"


def _extract_charset(content_type: str) -> str:
    match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebFetchError(f"only http/https URLs supported, got: {parsed.scheme!r}")
    if not parsed.hostname:
        raise WebFetchError("URL has no hostname")


def _url_to_slug(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").replace("www.", "")
    path = parsed.path.strip("/").replace("/", "-")
    slug = re.sub(r"[^a-z0-9-]", "", f"{host}-{path}".lower())
    return slug[:80] or "page"


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")[-1]
    return path.replace("-", " ").replace("_", " ").replace(".pdf", "").title() or "Untitled"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
