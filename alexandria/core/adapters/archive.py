"""Archive adapter — extract and ingest from tar/zip/gz files.

Extracts supported file types from archives and processes them
through the standard ingest pipeline.
"""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alexandria.core.adapters.base import FetchedItem, SyncResult

SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf", ".json", ".yaml", ".yml", ".toml", ".rst", ".html"}


class ArchiveAdapter:
    """Extract and process files from tar/zip archives."""

    kind = "archive"

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        archive_path = Path(config["path"]).expanduser().resolve()
        if not archive_path.exists():
            return [], SyncResult(errors=[f"archive not found: {archive_path}"])

        result = SyncResult()
        items: list[FetchedItem] = []
        out_dir = workspace_path / "raw" / "archives" / archive_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            extracted = _extract_archive(archive_path, Path(tmp))
            if not extracted:
                result.errors.append(f"no supported files in {archive_path.name}")
                return items, result

            for file_path in extracted:
                try:
                    rel = file_path.relative_to(tmp)
                    dest = out_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    # For PDFs, extract text
                    if file_path.suffix.lower() == ".pdf":
                        content = _extract_pdf_text(file_path)
                        md_dest = dest.with_suffix(".md")
                        md_dest.write_text(content, encoding="utf-8")
                        # Also copy original PDF
                        import shutil
                        shutil.copy2(str(file_path), str(dest))
                        content_path = str(md_dest.relative_to(workspace_path))
                    else:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                        dest.write_text(content, encoding="utf-8")
                        content_path = str(dest.relative_to(workspace_path))

                    content_hash = hashlib.sha256(content.encode()).hexdigest()

                    items.append(FetchedItem(
                        source_type="archive",
                        event_type="extracted_file",
                        title=str(rel),
                        body=content[:500] if content else None,
                        occurred_at=datetime.now(UTC).isoformat(),
                        event_data={
                            "archive": archive_path.name,
                            "content_hash": content_hash,
                            "content_path": content_path,
                        },
                    ))
                    result.items_synced += 1
                except Exception as exc:
                    result.items_errored += 1
                    result.errors.append(f"{file_path.name}: {exc}")

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if "path" not in config:
            return ["'path' required (path to tar/zip file)"]
        return []


def _extract_archive(archive_path: Path, dest: Path) -> list[Path]:
    """Extract supported files from an archive. Returns list of extracted paths."""
    files: list[Path] = []

    if zipfile.is_zipfile(str(archive_path)):
        with zipfile.ZipFile(str(archive_path)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                ext = Path(info.filename).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    zf.extract(info, str(dest))
                    files.append(dest / info.filename)

    elif tarfile.is_tarfile(str(archive_path)):
        with tarfile.open(str(archive_path)) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                ext = Path(member.name).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    # Security: prevent path traversal
                    if member.name.startswith("/") or ".." in member.name:
                        continue
                    tf.extract(member, str(dest), filter="data")
                    files.append(dest / member.name)
    else:
        raise ValueError(f"unsupported archive format: {archive_path.suffix}")

    return sorted(files)


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF file."""
    try:
        from alexandria.core.pdf import pdf_to_markdown
        return pdf_to_markdown(path)
    except Exception:
        return f"[PDF: {path.name} — text extraction failed]"
