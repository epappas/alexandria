"""Conversation capture — parse agent transcripts into wiki-ready documents.

Detects Claude Code JSONL format, Codex CLI logs, and plain markdown.
Each session becomes one markdown document in raw/conversations/.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CaptureError(Exception):
    pass


def _read_first_line(path: Path) -> str | None:
    """Read the first non-empty line from a file."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                return line
    return None


def detect_format(path: Path) -> str:
    """Detect the transcript format. Returns 'claude-code' | 'codex' | 'markdown' | 'unknown'."""
    if not path.exists():
        raise CaptureError(f"transcript not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        # Scan first few lines — first line may be metadata, not a message
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[:10]
        except OSError:
            return "unknown"
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # Claude Code: has "type" field with user/assistant/permission-mode
            if obj.get("type") in ("user", "human", "assistant", "permission-mode"):
                return "claude-code"
            # Codex: has role + content directly
            if "role" in obj and "content" in obj and "type" not in obj:
                return "codex"
        return "unknown"

    if suffix in (".md", ".txt"):
        return "markdown"

    return "unknown"


def capture_conversation(
    transcript_path: Path,
    workspace_path: Path,
    client: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Parse a transcript and write it as a markdown file.

    Returns metadata about the capture: session_id, output_path, content_hash, message_count.
    """
    fmt = detect_format(transcript_path)
    if fmt == "unknown":
        raise CaptureError(f"unrecognized transcript format: {transcript_path}")

    if fmt == "claude-code":
        messages = _parse_claude_code_jsonl(transcript_path)
    elif fmt == "codex":
        messages = _parse_codex_jsonl(transcript_path)
    else:
        messages = _parse_markdown(transcript_path)

    if not messages:
        raise CaptureError(f"no messages found in {transcript_path}")

    if not session_id:
        session_id = _derive_session_id(transcript_path)
    session_id = _validate_session_id(session_id)

    # Build markdown document
    content = _build_markdown(messages, client, session_id)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Write to raw/conversations/
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir = workspace_path / "raw" / "conversations" / client
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}-{session_id[:16]}.md"
    out_path.write_text(content, encoding="utf-8")

    return {
        "session_id": session_id,
        "output_path": str(out_path.relative_to(workspace_path)),
        "absolute_path": str(out_path),
        "content_hash": content_hash,
        "message_count": len(messages),
        "client": client,
        "format": fmt,
    }


def _parse_claude_code_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse Claude Code's JSONL transcript format."""
    messages: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type", "")
        if msg_type not in ("user", "human", "assistant"):
            continue
        role = "user" if msg_type in ("user", "human") else "assistant"
        content = _extract_text_content(obj.get("message", {}))
        # Skip empty messages and bare tool-call lines
        stripped = content.strip()
        if not stripped or stripped.startswith("[tool:"):
            continue
        messages.append({
            "role": role,
            "content": content,
            "timestamp": obj.get("timestamp", ""),
        })
    return messages


def _parse_codex_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse Codex CLI session log."""
    messages: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        role = obj.get("role", "")
        content = obj.get("content", "")
        if role and content:
            messages.append({
                "role": role,
                "content": content if isinstance(content, str) else json.dumps(content),
                "timestamp": obj.get("timestamp", ""),
            })
    return messages


def _parse_markdown(path: Path) -> list[dict[str, Any]]:
    """Parse a plain markdown transcript."""
    content = path.read_text(encoding="utf-8")
    return [{"role": "document", "content": content, "timestamp": ""}]


def _extract_text_content(message: dict[str, Any]) -> str:
    """Extract text from Claude API message content blocks."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    parts.append(f"[tool: {block.get('name', '')}]")
        return "\n".join(parts)
    return str(content)


def _validate_session_id(session_id: str) -> str:
    """Validate session_id is safe for use in file paths."""
    if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
        raise CaptureError(f"invalid session_id: {session_id!r}")
    # Strip to alphanumeric + dash + underscore
    clean = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    if not clean:
        raise CaptureError(f"session_id contains no valid characters: {session_id!r}")
    return clean


def _derive_session_id(path: Path) -> str:
    """Derive a stable session ID from the transcript path."""
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]


def _build_markdown(
    messages: list[dict[str, Any]], client: str, session_id: str
) -> str:
    """Build a markdown document from parsed messages."""
    lines = [
        f"# Conversation — {client}",
        "",
        f"- session: {session_id}",
        f"- captured: {datetime.now(UTC).isoformat()}",
        f"- messages: {len(messages)}",
        "", "---", "",
    ]

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")

        header = f"## {role.title()}"
        if ts:
            header += f" ({ts[:19]})"
        lines.append(header)
        lines.append("")
        lines.append(content)
        lines.append("")

    return "\n".join(lines)
