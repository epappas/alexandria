"""Tests for the skill installer (claude-code, cursor, codex)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alexandria.cli.skill_cmd import _install_claude_code, _install_cursor, _install_codex


def test_claude_code_skill_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    _install_claude_code()

    skill = tmp_path / ".claude" / "skills" / "alexandria" / "SKILL.md"
    assert skill.exists()
    assert "alexandria" in skill.read_text(encoding="utf-8")

    claude_md = tmp_path / ".claude" / "CLAUDE.md"
    assert claude_md.exists()
    assert "alexandria" in claude_md.read_text(encoding="utf-8")


def test_cursor_rule_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _install_cursor()
    rule = tmp_path / ".cursor" / "rules" / "alexandria.mdc"
    assert rule.exists()
    body = rule.read_text(encoding="utf-8")
    assert "alwaysApply: true" in body
    assert "alexandria" in body


def test_codex_hook_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _install_codex()

    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    assert "alexandria" in agents_md.read_text(encoding="utf-8")

    hooks_path = tmp_path / ".codex" / "hooks.json"
    assert hooks_path.exists()
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "PreToolUse" in hooks
    alxia_hook = [h for h in hooks["PreToolUse"] if h.get("_alexandria_managed")]
    assert len(alxia_hook) == 1


def test_codex_hook_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _install_codex()
    _install_codex()
    hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    alxia_hooks = [h for h in hooks["PreToolUse"] if h.get("_alexandria_managed")]
    assert len(alxia_hooks) == 1  # no duplicates
