"""Tests for hook installers."""

import json
from pathlib import Path

import pytest

from llmwiki.hooks.installer.claude_code import (
    HOOK_PROTOCOL_VERSION,
    install_claude_code_hooks,
    uninstall_claude_code_hooks,
    verify_claude_code_hooks,
)


class TestClaudeCodeHooks:
    def test_install(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = install_claude_code_hooks()
        assert "Stop" in result["hooks_installed"]
        assert "PreCompact" in result["hooks_installed"]
        assert settings.exists()

        config = json.loads(settings.read_text())
        assert "Stop" in config["hooks"]
        assert config["hooks"]["Stop"]["_llmwiki_managed"] is True

    def test_install_with_workspace(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = install_claude_code_hooks(workspace="myproject")
        config = json.loads(settings.read_text())
        assert "--workspace myproject" in config["hooks"]["Stop"]["command"]

    def test_uninstall(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        removed = uninstall_claude_code_hooks()
        assert removed is True

        config = json.loads(settings.read_text())
        assert "Stop" not in config.get("hooks", {})

    def test_uninstall_no_hooks(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        removed = uninstall_claude_code_hooks()
        assert removed is False

    def test_verify_installed(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        result = verify_claude_code_hooks()
        assert result["installed"] is True
        assert len(result["issues"]) == 0

    def test_verify_not_installed(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        result = verify_claude_code_hooks()
        assert result["installed"] is False
        assert len(result["issues"]) > 0

    def test_verify_version_mismatch(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        install_claude_code_hooks()
        # Tamper with version
        config = json.loads(settings.read_text())
        config["hooks"]["Stop"]["_protocol_version"] = 999
        settings.write_text(json.dumps(config))

        result = verify_claude_code_hooks()
        assert result["installed"] is False
        assert any("version mismatch" in i for i in result["issues"])

    def test_preserves_existing_settings(self, tmp_path: Path, monkeypatch) -> None:
        settings = tmp_path / "settings.local.json"
        monkeypatch.setattr(
            "llmwiki.hooks.installer.claude_code.SETTINGS_PATH", settings
        )
        # Pre-existing settings
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"custom_key": "preserved"}))

        install_claude_code_hooks()
        config = json.loads(settings.read_text())
        assert config["custom_key"] == "preserved"
        assert "hooks" in config
