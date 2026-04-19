"""Source adapter protocol.

Per ``05_source_integrations.md``: all sources implement one interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class AdapterKind(StrEnum):
    LOCAL = "local"
    GIT_LOCAL = "git-local"
    GITHUB = "github"


@dataclass
class FetchedItem:
    """A single item fetched from a source."""

    source_type: str
    event_type: str
    title: str
    body: str | None = None
    url: str | None = None
    author: str | None = None
    occurred_at: str = ""
    event_data: dict[str, Any] = field(default_factory=dict)
    # For file-based sources: the content to store in raw/
    raw_content: bytes | None = None
    raw_filename: str | None = None


@dataclass
class SyncResult:
    """Summary of a sync operation."""

    items_synced: int = 0
    items_errored: int = 0
    errors: list[str] = field(default_factory=list)


class SourceAdapter(Protocol):
    """Interface every source adapter must satisfy."""

    kind: AdapterKind

    def sync(
        self,
        workspace_path: Path,
        config: dict[str, Any],
    ) -> tuple[list[FetchedItem], SyncResult]:
        """Run a sync cycle. Returns fetched items and a summary."""
        ...

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """Validate adapter-specific config. Returns list of error messages."""
        ...
