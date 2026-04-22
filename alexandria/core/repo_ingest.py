"""Repo ingestion — clone/open a repository and ingest all supported files.

Handles both local directories and remote git URLs. Walks the tree,
filters by supported extensions, and batches through the ingest pipeline.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alexandria.core.code import LANG_EXTENSIONS
from alexandria.core.ingest import IngestError, IngestResult, ingest_file

# Extensions we ingest from repos
_CODE_EXTS = set(LANG_EXTENSIONS.keys())
_DOC_EXTS = {".md", ".txt", ".rst", ".adoc"}
_CONFIG_EXTS = {".toml", ".ini", ".cfg", ".json"}
ALL_INGEST_EXTS = _CODE_EXTS | _DOC_EXTS | _CONFIG_EXTS

# Directories to skip
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "target", "build", "dist", ".next", ".nuxt", "coverage",
    ".terraform", ".terragrunt-cache",
    "subagents", "tasks",  # Claude Code internal
}

# Files to skip
_SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "go.sum", "poetry.lock", "uv.lock",
}

# File patterns to skip
_SKIP_SUFFIXES = {".meta.json", ".lock"}

# Max file size to ingest (500 KB)
_MAX_FILE_SIZE = 500_000


@dataclass
class RepoIngestResult:
    """Summary of a repo ingestion run."""

    repo_path: str
    committed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.committed) + len(self.rejected) + len(self.skipped) + len(self.errors)


def clone_repo(url: str, dest: Path) -> Path:
    """Clone a git repo to dest. Returns the repo directory path."""
    slug = hashlib.sha256(url.encode()).hexdigest()[:12]
    name = url.rstrip("/").split("/")[-1].replace(".git", "")
    repo_dir = dest / f"{name}-{slug}"

    if (repo_dir / ".git").is_dir():
        # Already cloned — pull latest
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--quiet", "--ff-only"],
            capture_output=True, text=True, timeout=120,
        )
        return repo_dir

    repo_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--quiet", "--depth=1", url, str(repo_dir)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise IngestError(f"git clone failed: {result.stderr.strip()}")
    return repo_dir


def ingest_repo(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    repo_path: Path,
    *,
    topic: str | None = None,
    extensions: set[str] | None = None,
    on_progress: Any = None,
    no_merge: bool = False,
    scope: str = "all",
    should_cancel: Any = None,
    on_start: Any = None,
) -> RepoIngestResult:
    """Walk a repo directory and ingest all supported files.

    Args:
        repo_path: Path to the repo root (local or cloned).
        topic: Override topic for all files. Default: inferred from path.
        extensions: Override set of extensions to include.
        on_progress: Callable(file_path, status) for per-file progress.
        scope: 'all' (default) or 'docs' — docs limits to README/*.md +
            top-level markdown + docs/**/*.md only.
        should_cancel: Callable() -> bool. Checked between files; when
            True, the loop exits cleanly leaving committed files in place.
        on_start: Callable(total_files) invoked once with the file count
            after filtering. Lets callers populate a progress bar or
            persist the expected total before the first file runs.
    """
    allowed = extensions or ALL_INGEST_EXTS
    result = RepoIngestResult(repo_path=str(repo_path))

    files = _collect_files(repo_path, allowed)
    if scope == "docs":
        files = _filter_docs_scope(files, repo_path)
    if on_start:
        try:
            on_start(len(files))
        except Exception:
            pass

    for file_path in files:
        if should_cancel and should_cancel():
            result.errors.append("cancelled by user request")
            break
        rel = str(file_path.relative_to(repo_path))
        file_topic = topic or _infer_topic_from_path(file_path, repo_path)

        try:
            # Route JSONL conversation transcripts through capture
            if file_path.suffix == ".jsonl":
                ir = _ingest_conversation_file(
                    home, workspace_slug, workspace_path, file_path, file_topic,
                )
            else:
                ir = ingest_file(
                    home=home,
                    workspace_slug=workspace_slug,
                    workspace_path=workspace_path,
                    source_file=file_path,
                    topic=file_topic,
                    no_merge=no_merge,
                )
        except (IngestError, Exception) as exc:
            result.errors.append(f"{rel}: {exc}")
            if on_progress:
                on_progress(rel, "error")
            continue

        if ir is None:
            result.skipped.append(rel)
            if on_progress:
                on_progress(rel, "skipped")
            continue

        if ir.committed:
            result.committed.extend(ir.committed_paths)
        elif "content unchanged" in (ir.verdict_reasoning or ""):
            result.skipped.append(rel)
            if on_progress:
                on_progress(rel, "skipped")
            continue
        else:
            result.rejected.append(rel)

        if on_progress:
            on_progress(rel, "committed" if ir.committed else "rejected")

    return result


def _filter_docs_scope(files: list[Path], repo_path: Path) -> list[Path]:
    """Restrict a file list to documentation surfaces.

    Matches README*, LICENSE, top-level *.md / *.rst, and anything under
    docs/ (case-insensitive). Used by scope='docs' ingests to keep
    repository ingestion tractable.
    """
    kept: list[Path] = []
    for f in files:
        rel = f.relative_to(repo_path)
        parts = [p.lower() for p in rel.parts]
        name = f.name.lower()
        if parts and parts[0] in ("docs", "doc", "documentation"):
            kept.append(f)
            continue
        if len(parts) == 1 and (
            name.startswith("readme")
            or name.startswith("changelog")
            or name.startswith("contributing")
            or f.suffix.lower() in (".md", ".rst", ".txt")
        ):
            kept.append(f)
            continue
    return kept


def _collect_files(repo_path: Path, allowed_exts: set[str]) -> list[Path]:
    """Walk the repo tree and collect files matching allowed extensions.

    Also collects .jsonl conversation transcripts (Claude Code, Codex).
    """
    files: list[Path] = []
    for item in sorted(repo_path.rglob("*")):
        if not item.is_file():
            continue
        rel_parts = item.relative_to(repo_path).parts
        # Skip hidden files/dirs
        if any(part.startswith(".") and part != "." for part in rel_parts):
            continue
        # Skip known directories
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        # Skip lock and metadata files
        if item.name in _SKIP_FILES:
            continue
        if any(item.name.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        # JSONL conversation transcripts — always collect
        if item.suffix == ".jsonl":
            if item.stat().st_size > 0:
                files.append(item)
            continue
        # Check extension
        if item.suffix.lower() not in allowed_exts:
            continue
        # Skip large files
        if item.stat().st_size > _MAX_FILE_SIZE:
            continue
        files.append(item)
    return files


def _ingest_conversation_file(
    home: Path,
    workspace_slug: str,
    workspace_path: Path,
    jsonl_path: Path,
    topic: str,
) -> IngestResult | None:
    """Capture a JSONL conversation and ingest it. Returns None if not a conversation."""
    from alexandria.core.capture.conversation import (
        CaptureError,
        capture_conversation,
        detect_format,
    )
    fmt = detect_format(jsonl_path)
    if fmt == "unknown":
        return None

    try:
        cap = capture_conversation(jsonl_path, workspace_path, client=fmt)
    except CaptureError:
        return None

    md_path = Path(cap["absolute_path"])
    return ingest_file(
        home=home,
        workspace_slug=workspace_slug,
        workspace_path=workspace_path,
        source_file=md_path,
        topic=topic or "conversations",
    )


def _infer_topic_from_path(file_path: Path, repo_root: Path) -> str:
    """Infer a topic from the file's directory structure within the repo."""
    rel = file_path.relative_to(repo_root)
    parts = rel.parts[:-1]  # directory parts, without filename

    # Use the repo name as a base
    repo_name = repo_root.name.split("-")[0]  # strip hash suffix

    if not parts:
        return repo_name
    # Use first meaningful directory
    for part in parts:
        if part not in ("src", "lib", "pkg", "cmd", "internal", "app"):
            return f"{repo_name}/{part}"
    return repo_name
