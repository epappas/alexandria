"""Configuration loader for alexandria.

Reads ``~/.alexandria/config.toml`` into typed pydantic models, with environment
variable overrides for ``ALEXANDRIA_HOME`` and ``ALEXANDRIA_WORKSPACE``.

Design notes:
- Defaults match the architecture's ``01_vision_and_principles.md`` invariants.
- Fail-fast on bad config — pydantic raises with a clear field path.
- The config file is written if missing on first ``alexandria init``.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_HOME = Path.home() / ".alexandria"
DEFAULT_WORKSPACE_SLUG = "global"


class GeneralConfig(BaseModel):
    """Top-level alexandria settings."""

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


class LLMConfig(BaseModel):
    """LLM inference configuration."""

    provider: str = "anthropic"  # anthropic | openai | openai-compat
    model: str = ""  # empty = provider default
    api_key_env: str = ""  # env var name holding the key (e.g. ANTHROPIC_API_KEY)
    base_url: str = ""  # for openai-compat (ollama, vllm, etc.)


class SecretsConfig(BaseModel):
    """Pointer to secret storage."""

    keyring_service: str = "alexandria"


class BotConfig(BaseModel):
    """Chat-bot runtime configuration (Telegram, etc.)."""

    telegram_token_ref: str = "telegram_bot_token"
    telegram_allowlist: list[int] = Field(default_factory=list)
    workspace: str = ""  # empty = current workspace
    model: str = "haiku"  # passed to `claude -p --model`
    max_reply_chars: int = 3500  # stay under Telegram's 4096 limit
    agent_timeout_s: int = 180


class JobsConfig(BaseModel):
    """Background job worker configuration.

    The worker runs ingest work async so the interactive agent is not
    blocked. ``model`` controls which Claude model the worker pins for
    its LLM calls — it is always set on the worker subprocess env
    regardless of what the surrounding session uses, so ingests never
    consume Opus quota unintentionally.
    """

    model: str = "haiku"          # pinned for ingest LLM calls
    poll_interval_s: float = 1.0  # how often the worker polls the queue
    default_wait_s: int = 60      # default `ingest(wait_s=...)` in MCP tool


class Config(BaseModel):
    """The complete alexandria configuration."""

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    state: StateConfig = Field(default_factory=StateConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    bot: BotConfig = Field(default_factory=BotConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)


def resolve_home() -> Path:
    """Return the alexandria data directory, honoring ``ALEXANDRIA_HOME``."""
    env = os.environ.get("ALEXANDRIA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_HOME


def resolve_workspace(config: Config) -> str:
    """Return the active workspace slug, honoring ``ALEXANDRIA_WORKSPACE``."""
    env = os.environ.get("ALEXANDRIA_WORKSPACE")
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
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(v) for v in value) + "]"
    return f'"{str(value)}"'
