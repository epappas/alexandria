"""PDF text extraction for the ingest pipeline.

Uses pymupdf (fitz) to extract text from PDF files, preserving page
boundaries and basic structure. Handles multi-page documents, embedded
metadata, and falls back gracefully if pymupdf is not installed.

Extraction runs in a fresh subprocess with a hard wall-clock timeout:
a pymupdf hang on a malformed PDF cannot be interrupted from Python
(the parser is C code), so we isolate it and kill the subprocess if it
exceeds the budget.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing as mp
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PDF_MAGIC = b"%PDF-"
PDF_EXTRACT_TIMEOUT_S = 120


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


def extract_pdf(
    path: Path, *, timeout_s: int = PDF_EXTRACT_TIMEOUT_S,
) -> PDFDocument:
    """Extract text and metadata from a PDF file.

    Validates the file is an actual PDF (magic bytes) before invoking
    pymupdf, then runs extraction in a spawn-context subprocess that we
    can kill on timeout. Raises ``PDFExtractionError`` on missing file,
    non-PDF content, parser failure, or extraction timeout.
    """
    if not path.exists():
        raise PDFExtractionError(f"PDF not found: {path}")
    if not path.suffix.lower() == ".pdf":
        raise PDFExtractionError(f"not a PDF file: {path}")
    with path.open("rb") as f:
        head = f.read(len(PDF_MAGIC))
    if not head.startswith(PDF_MAGIC):
        raise PDFExtractionError(
            f"file does not start with PDF magic bytes (%PDF-): {path}"
        )

    ctx = mp.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=1, mp_context=ctx,
    ) as pool:
        future = pool.submit(_extract_pdf_in_subprocess, str(path))
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError as exc:
            for p in list(pool._processes.values()):
                p.kill()
            raise PDFExtractionError(
                f"PDF extraction timed out after {timeout_s}s: {path}"
            ) from exc


def _extract_pdf_in_subprocess(path_str: str) -> PDFDocument:
    """Run pymupdf in the worker subprocess. Must stay picklable."""
    import pymupdf  # core dependency since 0.37.1

    path = Path(path_str)
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PDFExtractionError(f"failed to open PDF: {exc}") from exc

    metadata = doc.metadata or {}
    title = (
        metadata.get("title", "").strip()
        or path.stem.replace("-", " ").replace("_", " ").title()
    )
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
