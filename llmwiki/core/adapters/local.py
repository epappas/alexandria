"""Local filesystem source adapter.

Walks a configured directory, returns files matching glob patterns as items.
Supports incremental sync via content hashing.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmwiki.core.adapters.base import AdapterKind, FetchedItem, SyncResult


class LocalAdapter:
    """Walk a local directory and fetch matching files."""

    kind = AdapterKind.LOCAL

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        source_dir = Path(config["path"]).expanduser().resolve()
        if not source_dir.is_dir():
            return [], SyncResult(errors=[f"source path not found: {source_dir}"])

        globs = config.get("globs", ["*.md", "*.txt"])
        raw_dir = workspace_path / "raw" / "local"
        raw_dir.mkdir(parents=True, exist_ok=True)

        known_hashes = self._load_known_hashes(raw_dir)
        items: list[FetchedItem] = []
        result = SyncResult()

        for pattern in globs:
            for path in sorted(source_dir.rglob(pattern)):
                if not path.is_file():
                    continue
                try:
                    content = path.read_bytes()
                except (OSError, PermissionError) as exc:
                    result.items_errored += 1
                    result.errors.append(f"{path}: {exc}")
                    continue

                content_hash = hashlib.sha256(content).hexdigest()
                rel = str(path.relative_to(source_dir))
                if known_hashes.get(rel) == content_hash:
                    continue  # unchanged

                # Copy to raw/
                dest = raw_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                known_hashes[rel] = content_hash

                items.append(FetchedItem(
                    source_type="local",
                    event_type="file_sync",
                    title=path.name,
                    body=None,
                    occurred_at=datetime.now(timezone.utc).isoformat(),
                    raw_content=content,
                    raw_filename=rel,
                    event_data={"path": rel, "size": len(content), "hash": content_hash},
                ))
                result.items_synced += 1

        self._save_known_hashes(raw_dir, known_hashes)
        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "path" not in config:
            errors.append("'path' is required for local adapter")
        else:
            p = Path(config["path"]).expanduser()
            if not p.is_dir():
                errors.append(f"path does not exist or is not a directory: {p}")
        return errors

    def _load_known_hashes(self, raw_dir: Path) -> dict[str, str]:
        hashfile = raw_dir / ".sync_hashes.json"
        if not hashfile.exists():
            return {}
        import json
        return json.loads(hashfile.read_text(encoding="utf-8"))

    def _save_known_hashes(self, raw_dir: Path, hashes: dict[str, str]) -> None:
        import json
        hashfile = raw_dir / ".sync_hashes.json"
        hashfile.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
