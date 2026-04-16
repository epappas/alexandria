"""Configuration loader for llmwiki.

Reads ``~/.llmwiki/config.toml`` into typed pydantic models, with environment
variable overrides for ``LLMWIKI_HOME`` and ``LLMWIKI_WORKSPACE``.

Design notes:
- Defaults match the architecture's ``01_vision_and_principles.md`` invariants.
- Fail-fast on bad config — pydantic raises with a clear field path.
- The config file is written if missing on first ``llmwiki init``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_HOME = Path.home() / ".llmwiki"
DEFAULT_WORKSPACE_SLUG = "global"


class GeneralConfig(BaseModel):
    """Top-level llmwiki settings."""

    data_dir: str = str(DEFAULT_HOME)
    editor: str | None = None


class StateConfig(BaseModel):
    """Mutable runtime state (e.g. current workspace)."""

    current_workspace: str = DEFAULT_WORKSPACE_SLUG


class DaemonConfig(BaseModel):
    """Optional daemon settings (Phase 6+)."""

    enabled: bool = False
    port: int = 7219
    web_ui: bool = True
    mcp_http: bool = True


class LimitsConfig(BaseModel):
    """Per-workspace soft limits."""

    max_pages_per_workspace: int = 2000
    max_tokens_per_ingest: int = 200_000


class SecretsConfig(BaseModel):
    """Pointer to secret storage (vault arrives in Phase 4)."""

    keyring_service: str = "llmwiki"


class Config(BaseModel):
    """The complete llmwiki configuration."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)


def resolve_home() -> Path:
    """Return the llmwiki data directory, honoring ``LLMWIKI_HOME``."""
    env = os.environ.get("LLMWIKI_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_HOME


def resolve_workspace(config: Config) -> str:
    """Return the active workspace slug, honoring ``LLMWIKI_WORKSPACE``."""
    env = os.environ.get("LLMWIKI_WORKSPACE")
    if env:
        return env
    return config.state.current_workspace


def config_path(home: Path) -> Path:
    return home / "config.toml"


def load_config(home: Path) -> Config:
    """Load config from ``<home>/config.toml`` or return defaults."""
    path = config_path(home)
    if not path.exists():
        return Config()
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return Config(**raw)


def write_default_config(home: Path) -> Path:
    """Write the default config to disk if missing. Returns the path."""
    path = config_path(home)
    if path.exists():
        return path
    home.mkdir(parents=True, exist_ok=True)
    cfg = Config(general=GeneralConfig(data_dir=str(home)))
    _write_toml(path, cfg.model_dump())
    return path


def save_config(home: Path, config: Config) -> Path:
    """Persist a config to disk, atomically."""
    path = config_path(home)
    home.mkdir(parents=True, exist_ok=True)
    _write_toml(path, config.model_dump())
    return path


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Render a dict as TOML manually (stdlib has only the reader)."""
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_format_toml_value(value)}")
        lines.append("")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    tmp.replace(path)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if value is None:
        return '""'
    return f'"{str(value)}"'
