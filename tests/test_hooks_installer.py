"""Tests for hook installers."""

import json
from pathlib import Path

import pytest

from alexandria.hooks.installer.claude_code import (
    install_claude_code_hooks,
    uninstall_claude_code_hooks,
    verify_claude_code_hooks,
)


class TestClaudeCodeHooks:
    def test_install(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = install_claude_code_hooks()
        assert "Stop" in result["hooks_installed"]
        assert "PreCompact" in result["hooks_installed"]
        assert settings.exists()

        config = json.loads(settings.read_text())
        assert "Stop" in config["hooks"]
        # Hooks are arrays of matcher objects
        assert isinstance(config["hooks"]["Stop"], list)
        assert config["hooks"]["Stop"][0]["_alexandria_managed"] is True
        assert config["hooks"]["Stop"][0]["hooks"][0]["type"] == "command"

    def test_install_with_workspace(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = install_claude_code_hooks(workspace="myproject")
        config = json.loads(settings.read_text())
        cmd = config["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "--workspace myproject" in cmd

    def test_uninstall(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        removed = uninstall_claude_code_hooks()
        assert removed is True

        config = json.loads(settings.read_text())
        # After uninstall, arrays should be empty
        assert config["hooks"]["Stop"] == []

    def test_uninstall_no_hooks(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        removed = uninstall_claude_code_hooks()
        assert removed is False

    def test_verify_installed(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        result = verify_claude_code_hooks()
        assert result["installed"] is True
        assert len(result["issues"]) == 0

    def test_verify_not_installed(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = verify_claude_code_hooks()
        assert result["installed"] is False
        assert len(result["issues"]) > 0

    def test_preserves_existing_settings(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"custom_key": "preserved"}))

        install_claude_code_hooks()
        config = json.loads(settings.read_text())
        assert config["custom_key"] == "preserved"
        assert "hooks" in config

    def test_idempotent_install(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "alexandria.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        install_claude_code_hooks()  # second install
        config = json.loads(settings.read_text())
        # Should have exactly 1 entry per event, not duplicates
        assert len(config["hooks"]["Stop"]) == 1
        assert len(config["hooks"]["PreCompact"]) == 1
