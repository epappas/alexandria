"""Tests for `alxia bot status` and basic CLI wiring."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from alexandria.cli.main import app


def test_bot_status_reports_missing_token_and_empty_allowlist(
    initialized_home: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    monkeypatch.delenv("ALEXANDRIA_TELEGRAM_BOT_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["bot", "status"])
    assert result.exit_code == 0, result.stdout
    assert "missing" in result.stdout.lower()
    assert "Allowlist size:  0" in result.stdout
    assert "telegram_bot_token" in result.stdout


def test_bot_status_reports_env_token(
    initialized_home: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    monkeypatch.setenv("ALEXANDRIA_TELEGRAM_BOT_TOKEN", "secret-dev-token")
    runner = CliRunner()
    result = runner.invoke(app, ["bot", "status"])
    assert result.exit_code == 0
    assert "Token:           set" in result.stdout


def test_bot_start_rejects_unknown_platform(
    initialized_home: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    runner = CliRunner()
    result = runner.invoke(app, ["bot", "start", "--platform", "signal"])
    assert result.exit_code == 1
    assert "Unknown platform" in result.stdout


def test_bot_start_fails_without_allowlist(
    initialized_home: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    monkeypatch.setenv("ALEXANDRIA_TELEGRAM_BOT_TOKEN", "dev")
    runner = CliRunner()
    result = runner.invoke(app, ["bot", "start"])
    assert result.exit_code == 1
    assert "allowlist is empty" in result.stdout
