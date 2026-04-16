"""Tests for ``alexandria.config`` against real filesystem (no mocks)."""

from __future__ import annotations

from pathlib import Path

import pytest

from alexandria.config import (
    DEFAULT_HOME,
    DEFAULT_WORKSPACE_SLUG,
    Config,
    GeneralConfig,
    StateConfig,
    config_path,
    load_config,
    resolve_home,
    resolve_workspace,
    save_config,
    write_default_config,
)


def test_resolve_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALEXANDRIA_HOME", raising=False)
    assert resolve_home() == DEFAULT_HOME


def test_resolve_home_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    monkeypatch.setenv("ALEXANDRIA_HOME", str(custom))
    assert resolve_home() == custom.resolve()


def test_load_config_returns_defaults_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "alexandria"
    cfg = load_config(home)
    assert cfg.state.current_workspace == DEFAULT_WORKSPACE_SLUG
    assert cfg.general.data_dir == str(DEFAULT_HOME)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    home = tmp_path / "alexandria"
    cfg = Config(
        general=GeneralConfig(data_dir=str(home), editor="nvim"),
        state=StateConfig(current_workspace="research"),
    )
    save_config(home, cfg)
    loaded = load_config(home)
    assert loaded.state.current_workspace == "research"
    assert loaded.general.editor == "nvim"
    assert loaded.general.data_dir == str(home)


def test_write_default_config_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "alexandria"
    first = write_default_config(home)
    assert first == config_path(home)
    assert first.exists()
    # Re-running should be a no-op.
    second = write_default_config(home)
    assert second == first
    # Content untouched.
    assert load_config(home).state.current_workspace == DEFAULT_WORKSPACE_SLUG


def test_resolve_workspace_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEXANDRIA_WORKSPACE", "customer-acme")
    cfg = Config()
    assert resolve_workspace(cfg) == "customer-acme"


def test_resolve_workspace_uses_state_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALEXANDRIA_WORKSPACE", raising=False)
    cfg = Config(state=StateConfig(current_workspace="research"))
    assert resolve_workspace(cfg) == "research"
