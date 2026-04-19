"""Watch mode — auto-ingest files on change.

Uses watchdog for cross-platform filesystem events with debouncing.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from alexandria.core.repo_ingest import ALL_INGEST_EXTS, _SKIP_DIRS, _SKIP_FILES, _SKIP_SUFFIXES


def start_watcher(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    watch_path: Path,
    *,
    debounce_ms: int = 500,
    on_progress: Callable[[str, str], None] | None = None,
) -> None:
    """Watch a directory and auto-ingest changed files. Blocks until interrupted."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileSystemEvent
    except ImportError:
        raise RuntimeError(
            "watchdog not installed. Run: pip install 'alexandria-wiki[watch]'"
        )

    handler = _IngestHandler(
        home, workspace_slug, workspace_path, watch_path,
        debounce_ms=debounce_ms, on_progress=on_progress,
    )
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=True)
    observer.start()

    try:
        while True:
            handler.process_pending()
            time.sleep(debounce_ms / 1000)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


class _IngestHandler:
    """File event handler with debouncing and skip patterns."""

    def __init__(
        self,
        home: Path,
        workspace_slug: str,
        workspace_path: Path,
        watch_root: Path,
        *,
        debounce_ms: int = 500,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> None:
        self._home = home
        self._workspace_slug = workspace_slug
        self._workspace_path = workspace_path
        self._watch_root = watch_root
        self._debounce_s = debounce_ms / 1000
        self._on_progress = on_progress
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def dispatch(self, event: Any) -> None:
        """Called by watchdog on any filesystem event."""
        if getattr(event, "is_directory", False):
            return
        src = getattr(event, "src_path", "")
        if not src:
            return
        path = Path(src)
        if not self._should_ingest(path):
            return
        with self._lock:
            self._pending[str(path)] = time.monotonic()

    def process_pending(self) -> None:
        """Ingest files that have been stable past the debounce window."""
        now = time.monotonic()
        ready: list[str] = []

        with self._lock:
            for path_str, ts in list(self._pending.items()):
                if now - ts >= self._debounce_s:
                    ready.append(path_str)
                    del self._pending[path_str]

        for path_str in ready:
            self._ingest(Path(path_str))

    def _should_ingest(self, path: Path) -> bool:
        """Check if a file should be ingested based on extension and skip patterns."""
        if path.suffix.lower() not in ALL_INGEST_EXTS and path.suffix != ".jsonl":
            return False
        try:
            rel_parts = path.relative_to(self._watch_root).parts
        except ValueError:
            return False
        if any(p.startswith(".") for p in rel_parts):
            return False
        if any(p in _SKIP_DIRS for p in rel_parts):
            return False
        if path.name in _SKIP_FILES:
            return False
        return not any(path.name.endswith(s) for s in _SKIP_SUFFIXES)

    def _ingest(self, path: Path) -> None:
        """Ingest a single file, reporting progress."""
        from alexandria.core.ingest import IngestError, ingest_file

        rel = str(path.relative_to(self._watch_root))
        try:
            result = ingest_file(
                home=self._home,
                workspace_slug=self._workspace_slug,
                workspace_path=self._workspace_path,
                source_file=path,
            )
            status = "committed" if result.committed else "skipped"
        except IngestError:
            status = "error"

        if self._on_progress:
            self._on_progress(rel, status)
