"""PDF text extraction for the ingest pipeline.

Uses pymupdf (fitz) to extract text from PDF files, preserving page
boundaries and basic structure. Handles multi-page documents, embedded
metadata, and falls back gracefully if pymupdf is not installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PDFExtractionError(Exception):
    pass


@dataclass
class PDFPage:
    """Extracted text from a single PDF page."""

    number: int  # 1-indexed
    text: str


@dataclass
class PDFDocument:
    """Extracted content from a PDF file."""

    path: str
    title: str
    author: str
    pages: list[PDFPage]
    page_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text.strip())

    def to_markdown(self) -> str:
        """Convert extracted PDF to markdown."""
        lines = [f"# {self.title}", ""]

        if self.author:
            lines.append(f"- author: {self.author}")
        lines.append(f"- pages: {self.page_count}")
        lines.append(f"- source: {self.path}")
        lines.extend(["", "---", ""])

        for page in self.pages:
            text = page.text.strip()
            if not text:
                continue
            lines.append(f"## Page {page.number}")
            lines.append("")
            lines.append(_clean_text(text))
            lines.append("")

        return "\n".join(lines)


def extract_pdf(path: Path) -> PDFDocument:
    """Extract text and metadata from a PDF file.

    Raises PDFExtractionError if pymupdf is not installed or the file
    cannot be parsed.
    """
    if not path.exists():
        raise PDFExtractionError(f"PDF not found: {path}")
    if not path.suffix.lower() == ".pdf":
        raise PDFExtractionError(f"not a PDF file: {path}")

    try:
        import pymupdf
    except ImportError:
        raise PDFExtractionError(
            "pymupdf is required for PDF ingestion. Install with: "
            "pip install pymupdf"
        )

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PDFExtractionError(f"failed to open PDF: {exc}") from exc

    metadata = doc.metadata or {}
    title = metadata.get("title", "").strip() or path.stem.replace("-", " ").replace("_", " ").title()
    author = metadata.get("author", "").strip()

    pages: list[PDFPage] = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append(PDFPage(number=i + 1, text=text))

    doc.close()

    return PDFDocument(
        path=str(path),
        title=title,
        author=author,
        pages=pages,
        page_count=len(pages),
        metadata={k: v for k, v in metadata.items() if v},
    )


def pdf_to_markdown(path: Path) -> str:
    """Extract a PDF and return its content as markdown."""
    doc = extract_pdf(path)
    return doc.to_markdown()


def _clean_text(text: str) -> str:
    """Clean up extracted PDF text."""
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Fix hyphenated line breaks (word- \nbreak -> wordbreak)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return text.strip()
