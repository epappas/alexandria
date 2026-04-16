"""Tests for conversation capture and format detection."""

import json
from pathlib import Path

import pytest

from alexandria.core.capture.conversation import (
    CaptureError,
    capture_conversation,
    detect_format,
)


@pytest.fixture
def claude_code_transcript(tmp_path: Path) -> Path:
    """Create a Claude Code JSONL transcript fixture."""
    lines = [
        json.dumps({"type": "human", "message": {"content": "What is alexandria?"}, "timestamp": "2025-01-15T10:00:00Z"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "alexandria is a knowledge engine."}]}, "timestamp": "2025-01-15T10:00:05Z"}),
        json.dumps({"type": "human", "message": {"content": "How does it work?"}, "timestamp": "2025-01-15T10:01:00Z"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "It accumulates knowledge from sources."}]}, "timestamp": "2025-01-15T10:01:10Z"}),
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def codex_transcript(tmp_path: Path) -> Path:
    lines = [
        json.dumps({"role": "user", "content": "Fix the bug", "timestamp": "2025-01-15T10:00:00Z"}),
        json.dumps({"role": "assistant", "content": "I'll fix it.", "timestamp": "2025-01-15T10:00:05Z"}),
    ]
    path = tmp_path / "codex-session.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def markdown_transcript(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text("# Meeting Notes\n\nDiscussed architecture.", encoding="utf-8")
    return path


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestDetectFormat:
    def test_claude_code(self, claude_code_transcript: Path) -> None:
        assert detect_format(claude_code_transcript) == "claude-code"

    def test_codex(self, codex_transcript: Path) -> None:
        assert detect_format(codex_transcript) == "codex"

    def test_markdown(self, markdown_transcript: Path) -> None:
        assert detect_format(markdown_transcript) == "markdown"

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CaptureError, match="not found"):
            detect_format(tmp_path / "nonexistent.jsonl")

    def test_unknown_format(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text("a,b,c\n1,2,3")
        assert detect_format(path) == "unknown"


class TestCaptureConversation:
    def test_capture_claude_code(self, claude_code_transcript, workspace_path) -> None:
        result = capture_conversation(
            claude_code_transcript, workspace_path, "claude-code"
        )
        assert result["message_count"] == 4
        assert result["format"] == "claude-code"
        assert result["client"] == "claude-code"
        assert result["content_hash"]

        # Verify file was written
        out_path = workspace_path / result["output_path"]
        assert out_path.exists()
        content = out_path.read_text()
        assert "alexandria is a knowledge engine" in content

    def test_capture_codex(self, codex_transcript, workspace_path) -> None:
        result = capture_conversation(
            codex_transcript, workspace_path, "codex"
        )
        assert result["message_count"] == 2
        assert result["format"] == "codex"

    def test_capture_markdown(self, markdown_transcript, workspace_path) -> None:
        result = capture_conversation(
            markdown_transcript, workspace_path, "plain"
        )
        assert result["message_count"] == 1

    def test_capture_unknown_format_raises(self, tmp_path, workspace_path) -> None:
        path = tmp_path / "data.bin"
        path.write_bytes(b"\x00\x01\x02")
        with pytest.raises(CaptureError, match="unrecognized"):
            capture_conversation(path, workspace_path, "test")

    def test_capture_empty_transcript_raises(self, tmp_path, workspace_path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        with pytest.raises(CaptureError):
            capture_conversation(path, workspace_path, "claude-code")

    def test_capture_with_session_id(self, claude_code_transcript, workspace_path) -> None:
        result = capture_conversation(
            claude_code_transcript, workspace_path, "claude-code",
            session_id="test-session-123",
        )
        assert result["session_id"] == "test-session-123"

    def test_repeated_capture_same_message_count(self, claude_code_transcript, workspace_path) -> None:
        r1 = capture_conversation(claude_code_transcript, workspace_path, "claude-code")
        r2 = capture_conversation(claude_code_transcript, workspace_path, "claude-code")
        assert r1["message_count"] == r2["message_count"]
        assert r1["format"] == r2["format"]
