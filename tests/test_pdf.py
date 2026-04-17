"""Tests for PDF extraction."""

from pathlib import Path

import pytest


def _create_test_pdf(path: Path, text: str = "Hello from a PDF document.") -> Path:
    """Create a minimal valid PDF with text content using pymupdf."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


class TestPDFExtraction:
    def test_extract_pdf(self, tmp_path: Path) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        from alexandria.core.pdf import extract_pdf

        pdf = _create_test_pdf(tmp_path / "test.pdf")
        doc = extract_pdf(pdf)
        assert doc.page_count == 1
        assert "Hello from a PDF" in doc.full_text
        assert doc.path == str(pdf)

    def test_pdf_to_markdown(self, tmp_path: Path) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        from alexandria.core.pdf import pdf_to_markdown

        pdf = _create_test_pdf(tmp_path / "test.pdf", "Transformers use self-attention mechanisms.")
        md = pdf_to_markdown(pdf)
        assert "# " in md  # has a title heading
        assert "Page 1" in md
        assert "self-attention" in md

    def test_multi_page(self, tmp_path: Path) -> None:
        pymupdf = pytest.importorskip("pymupdf")
        from alexandria.core.pdf import extract_pdf

        doc = pymupdf.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), f"Content on page {i + 1}")
        pdf_path = tmp_path / "multi.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = extract_pdf(pdf_path)
        assert result.page_count == 3
        assert "page 1" in result.full_text.lower()
        assert "page 3" in result.full_text.lower()

    def test_not_a_pdf(self, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        from alexandria.core.pdf import extract_pdf, PDFExtractionError

        txt = tmp_path / "readme.txt"
        txt.write_text("not a pdf")
        with pytest.raises(PDFExtractionError, match="not a PDF"):
            extract_pdf(txt)

    def test_nonexistent(self, tmp_path: Path) -> None:
        pytest.importorskip("pymupdf")
        from alexandria.core.pdf import extract_pdf, PDFExtractionError

        with pytest.raises(PDFExtractionError, match="not found"):
            extract_pdf(tmp_path / "missing.pdf")

    def test_ingest_pdf(self, tmp_path: Path) -> None:
        """End-to-end: ingest a PDF through the pipeline."""
        pymupdf = pytest.importorskip("pymupdf")
        import os
        from alexandria.db.connection import connect, db_path
        from alexandria.db.migrator import Migrator
        from alexandria.core.workspace import init_workspace

        home = tmp_path / "home"
        home.mkdir()
        os.environ["ALEXANDRIA_HOME"] = str(home)

        with connect(db_path(home)) as conn:
            Migrator().apply_pending(conn)
        init_workspace(home, "global", "Global", "Global workspace")

        ws_path = home / "workspaces" / "global"
        pdf = _create_test_pdf(tmp_path / "arxiv-paper.pdf", "Neural networks achieve state of the art results on benchmark tasks.")

        from alexandria.core.ingest import ingest_file
        result = ingest_file(home, "global", ws_path, pdf)

        assert result.committed
        assert len(result.committed_paths) >= 1

        # Verify the markdown was written
        wiki_dir = ws_path / "wiki"
        md_files = list(wiki_dir.rglob("*.md"))
        assert len(md_files) >= 1

        # Verify raw PDF was copied
        raw_dir = ws_path / "raw" / "local"
        assert (raw_dir / "arxiv-paper.pdf").exists()
        assert (raw_dir / "arxiv-paper.md").exists()

        os.environ.pop("ALEXANDRIA_HOME", None)
