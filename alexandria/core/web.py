"""Web page fetching and conversion to markdown.

Fetches a URL, extracts readable content, and converts to markdown.
Supports HTML pages and direct PDF URLs.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


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
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "footer", "header",
                              "iframe", "form", "aside", "noscript"]):
        tag.decompose()

    # Extract main content container
    main = _extract_main_content(soup)
    target_html = str(main) if main else str(soup.body or soup)

    try:
        from markdownify import markdownify
        md = markdownify(
            target_html, heading_style="ATX",
            strip=["select", "input", "button", "object", "embed"],
        )
    except ImportError:
        md = soup.get_text(separator="\n")

    # Clean up
    md = re.sub(r"\n{3,}", "\n\n", md)
    lines = md.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        # Skip bare short links and image-only lines
        if re.match(r"^\[.*\]\(.*\)$", stripped) and len(stripped) < 60:
            continue
        if stripped.startswith("[!["):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _extract_main_content(soup: BeautifulSoup) -> Tag | None:  # noqa: F821
    """Extract the main content element using BeautifulSoup.

    Tries common content containers in priority order.
    Returns the element, or None to fall back to full body.
    """
    from bs4 import Tag

    # Priority order: article > main > role=main > known IDs > known classes
    selectors = [
        lambda s: s.find("article"),
        lambda s: s.find("main"),
        lambda s: s.find(attrs={"role": "main"}),
        lambda s: s.find(id=re.compile(r"^(content|main-content|bodyContent|mw-content-text)$", re.I)),
        lambda s: s.find(class_=re.compile(r"(article-body|post-content|entry-content|paper-content)", re.I)),
    ]
    for selector in selectors:
        el = selector(soup)
        if isinstance(el, Tag) and len(el.get_text(strip=True)) > 200:
            return el
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
    from datetime import datetime
    return datetime.now(UTC).isoformat()
