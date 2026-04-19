"""Smart folder adapter — auto-discover and route files by type.

Walks a directory tree, detects file types, and routes each to the
appropriate handler: markdown/text directly, PDFs via extraction,
archives via extraction, and unsupported types are skipped with a log.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alexandria.core.adapters.base import FetchedItem, SyncResult

# Files we know how to handle
TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".org", ".adoc"}
DATA_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".csv", ".xml"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".sh"}
PDF_EXTENSIONS = {".pdf"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"}
HTML_EXTENSIONS = {".html", ".htm"}

ALL_SUPPORTED = TEXT_EXTENSIONS | DATA_EXTENSIONS | CODE_EXTENSIONS | PDF_EXTENSIONS | HTML_EXTENSIONS

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox",
             ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build"}


class FolderAdapter:
    """Smart folder discovery — auto-detect file types and ingest."""

    kind = "folder"

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        source_dir = Path(config["path"]).expanduser().resolve()
        if not source_dir.is_dir():
            return [], SyncResult(errors=[f"not a directory: {source_dir}"])

        result = SyncResult()
        items: list[FetchedItem] = []
        out_dir = workspace_path / "raw" / "folder" / source_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Load state for incremental sync
        state_file = out_dir / ".folder_state.json"
        known_hashes = _load_state(state_file)

        for path in _walk_files(source_dir):
            ext = path.suffix.lower()
            # Double extensions for archives
            if path.name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
                ext = "".join(path.suffixes[-2:])

            try:
                if ext in ARCHIVE_EXTENSIONS:
                    # Route to archive adapter
                    from alexandria.core.adapters.archive import ArchiveAdapter
                    adapter = ArchiveAdapter()
                    sub_items, sub_result = adapter.sync(workspace_path, {"path": str(path)})
                    items.extend(sub_items)
                    result.items_synced += sub_result.items_synced
                    result.items_errored += sub_result.items_errored
                    result.errors.extend(sub_result.errors)
                    continue

                if ext in PDF_EXTENSIONS:
                    content = _extract_pdf(path)
                elif ext in ALL_SUPPORTED:
                    content = path.read_text(encoding="utf-8", errors="replace")
                else:
                    continue  # skip unsupported

                content_hash = hashlib.sha256(content.encode()).hexdigest()
                rel = str(path.relative_to(source_dir))

                if known_hashes.get(rel) == content_hash:
                    continue  # unchanged

                # Save to raw
                dest = out_dir / rel
                if ext in PDF_EXTENSIONS:
                    dest = dest.with_suffix(".md")
                    import shutil
                    pdf_dest = out_dir / rel
                    pdf_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(path), str(pdf_dest))

                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                known_hashes[rel] = content_hash

                items.append(FetchedItem(
                    source_type="folder",
                    event_type="file_discovery",
                    title=path.name,
                    body=content[:300] if content else None,
                    occurred_at=datetime.now(timezone.utc).isoformat(),
                    event_data={
                        "path": rel,
                        "extension": ext,
                        "size": path.stat().st_size,
                        "content_hash": content_hash,
                        "content_path": str(dest.relative_to(workspace_path)),
                    },
                ))
                result.items_synced += 1
            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"{path.name}: {exc}")

        _save_state(state_file, known_hashes)
        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if "path" not in config:
            return ["'path' required"]
        return []


def _walk_files(root: Path) -> list[Path]:
    """Walk directory tree, skipping common non-content directories."""
    import os
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in sorted(filenames):
            if not f.startswith("."):
                files.append(Path(dirpath) / f)
    return files


def _extract_pdf(path: Path) -> str:
    try:
        from alexandria.core.pdf import pdf_to_markdown
        return pdf_to_markdown(path)
    except Exception:
        return f"[PDF: {path.name} — extraction failed]"


def _load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(path: Path, state: dict[str, str]) -> None:
    import json
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
