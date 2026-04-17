"""HuggingFace adapter — fetch model cards, dataset cards, and papers.

Uses the HuggingFace Hub API (no auth required for public repos).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from alexandria.core.adapters.base import FetchedItem, SyncResult

HF_API = "https://huggingface.co/api"


class HuggingFaceAdapter:
    """Fetch model cards, dataset cards, and README files from HuggingFace."""

    kind = "huggingface"

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        repos = config.get("repos", [])
        result = SyncResult()
        items: list[FetchedItem] = []
        out_dir = workspace_path / "raw" / "huggingface"
        out_dir.mkdir(parents=True, exist_ok=True)

        for repo_id in repos:
            try:
                readme = _fetch_readme(repo_id)
                if not readme:
                    result.items_errored += 1
                    result.errors.append(f"{repo_id}: no README found")
                    continue

                content_hash = hashlib.sha256(readme.encode()).hexdigest()
                slug = repo_id.replace("/", "--")
                md_path = out_dir / f"{slug}.md"

                lines = [
                    f"# {repo_id}",
                    "",
                    f"- source: https://huggingface.co/{repo_id}",
                    f"- fetched: {datetime.now(timezone.utc).isoformat()}",
                    "", "---", "",
                    readme,
                ]
                md_path.write_text("\n".join(lines), encoding="utf-8")

                items.append(FetchedItem(
                    source_type="huggingface",
                    event_type="model_card",
                    title=repo_id,
                    body=readme[:500],
                    url=f"https://huggingface.co/{repo_id}",
                    occurred_at=datetime.now(timezone.utc).isoformat(),
                    event_data={
                        "repo_id": repo_id,
                        "content_hash": content_hash,
                        "content_path": str(md_path.relative_to(workspace_path)),
                    },
                ))
                result.items_synced += 1
            except Exception as exc:
                result.items_errored += 1
                result.errors.append(f"{repo_id}: {exc}")

        return items, result

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if not config.get("repos"):
            return ["'repos' required (list of repo IDs like 'meta-llama/Llama-3-8b')"]
        return []


def _fetch_readme(repo_id: str) -> str | None:
    """Fetch the README.md from a HuggingFace repo."""
    url = f"https://huggingface.co/{repo_id}/raw/main/README.md"
    req = Request(url, headers={"User-Agent": "alexandria/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
