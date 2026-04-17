"""Tests for web URL fetching and conversion."""

from pathlib import Path

import pytest

from alexandria.core.web import (
    WebFetchError,
    _extract_title,
    _html_to_markdown,
    _url_to_slug,
    _validate_url,
    fetch_url,
    fetch_and_save,
)


class TestValidateUrl:
    def test_http(self) -> None:
        _validate_url("http://example.com")

    def test_https(self) -> None:
        _validate_url("https://arxiv.org/pdf/2401.12345")

    def test_rejects_ftp(self) -> None:
        with pytest.raises(WebFetchError, match="http/https"):
            _validate_url("ftp://example.com/file")

    def test_rejects_no_host(self) -> None:
        with pytest.raises(WebFetchError, match="hostname"):
            _validate_url("https://")


class TestExtractTitle:
    def test_basic(self) -> None:
        assert _extract_title("<html><title>My Page</title></html>") == "My Page"

    def test_no_title(self) -> None:
        assert _extract_title("<html><body>No title here</body></html>") == "Untitled"

    def test_html_entities(self) -> None:
        assert _extract_title("<title>A &amp; B</title>") == "A & B"


class TestHtmlToMarkdown:
    def test_basic(self) -> None:
        md = _html_to_markdown("<p>Hello <strong>world</strong></p>")
        assert "Hello" in md
        assert "world" in md

    def test_strips_scripts(self) -> None:
        md = _html_to_markdown("<p>Safe</p><script>alert(1)</script>")
        assert "alert" not in md

    def test_empty(self) -> None:
        assert _html_to_markdown("") == ""


class TestUrlToSlug:
    def test_basic(self) -> None:
        slug = _url_to_slug("https://arxiv.org/pdf/2401.12345")
        assert "arxiv" in slug
        assert len(slug) <= 80

    def test_long_url(self) -> None:
        slug = _url_to_slug("https://example.com/" + "a" * 200)
        assert len(slug) <= 80


class TestFetchUrl:
    def test_fetch_html(self, monkeypatch) -> None:
        html = b"<html><title>Test Page</title><body><p>Content here.</p></body></html>"

        class FakeResponse:
            headers = {"Content-Type": "text/html; charset=utf-8"}
            def read(self):
                return html
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        monkeypatch.setattr("alexandria.core.web.urlopen", lambda req, timeout: FakeResponse())
        result = fetch_url("https://example.com/page")
        assert result["title"] == "Test Page"
        assert result["content_type"] == "html"
        assert "Content here" in result["content"]

    def test_fetch_pdf(self, monkeypatch, tmp_path) -> None:
        pymupdf = pytest.importorskip("pymupdf")

        # Create a real PDF in memory
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Attention is all you need.")
        pdf_bytes = doc.tobytes()
        doc.close()

        class FakeResponse:
            headers = {"Content-Type": "application/pdf"}
            def read(self):
                return pdf_bytes
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        monkeypatch.setattr("alexandria.core.web.urlopen", lambda req, timeout: FakeResponse())
        result = fetch_url("https://arxiv.org/pdf/1706.03762.pdf")
        assert result["content_type"] == "pdf"
        assert "Attention" in result["content"]


class TestFetchAndSave:
    def test_saves_html(self, monkeypatch, tmp_path) -> None:
        html = b"<html><title>Saved Page</title><body><p>Saved content.</p></body></html>"

        class FakeResponse:
            headers = {"Content-Type": "text/html"}
            def read(self):
                return html
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        monkeypatch.setattr("alexandria.core.web.urlopen", lambda req, timeout: FakeResponse())
        ws = tmp_path / "workspace"
        ws.mkdir()

        path = fetch_and_save("https://example.com/article", ws)
        assert path.exists()
        assert path.suffix == ".md"
        content = path.read_text()
        assert "Saved Page" in content
        assert "source: https://example.com/article" in content
