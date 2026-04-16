"""Belief sidecar files — ``*.beliefs.json`` next to wiki pages.

Per ``19_belief_revision.md``: the wiki page remains the source of truth;
the sidecar is a machine-readable belief extract. Git-versioned alongside
the markdown. ``llmwiki reindex --rebuild-beliefs`` reconstructs the SQLite
table from the sidecars.
"""

from __future__ import annotations

import json
from pathlib import Path

from llmwiki.core.beliefs.model import Belief


def sidecar_path(page_path: Path) -> Path:
    """Return the sidecar path for a wiki page: same name with ``.beliefs.json``."""
    return page_path.with_suffix(".beliefs.json")


def write_sidecar(page_path: Path, beliefs: list[Belief]) -> Path:
    """Write beliefs to the sidecar JSON file next to the wiki page."""
    path = sidecar_path(page_path)
    payload = {
        "page": str(page_path.name),
        "beliefs": [b.to_dict() for b in beliefs],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_sidecar(page_path: Path, workspace: str = "") -> list[Belief]:
    """Read beliefs from a sidecar JSON file."""
    path = sidecar_path(page_path)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Belief.from_dict(b, workspace=workspace) for b in data.get("beliefs", [])]
