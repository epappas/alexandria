"""Hook installer for Codex CLI."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

HOOK_PROTOCOL_VERSION = 1
SETTINGS_PATH = Path.home() / ".codex" / "hooks.json"
MARKER = "_llmwiki_managed"


def install_codex_hooks(workspace: str | None = None) -> dict[str, Any]:
    """Install Stop + PreCompact hooks for Codex CLI."""
    llmwiki_bin = shutil.which("llmwiki") or f"{sys.executable} -m llmwiki"
    base_cmd = f"{llmwiki_bin} capture conversation --client codex --detach"
    if workspace:
        base_cmd += f" --workspace {workspace}"

    hooks = {
        "Stop": {"command": base_cmd, MARKER: True, "_protocol_version": HOOK_PROTOCOL_VERSION},
        "PreCompact": {
            "command": f"{base_cmd} --reason pre-compact",
            MARKER: True,
            "_protocol_version": HOOK_PROTOCOL_VERSION,
        },
    }

    config = _read_settings()
    if "hooks" not in config:
        config["hooks"] = {}
    for event, entry in hooks.items():
        config["hooks"][event] = entry
    _write_settings(config)

    return {
        "client": "codex",
        "settings_path": str(SETTINGS_PATH),
        "hooks_installed": list(hooks.keys()),
    }


def uninstall_codex_hooks() -> bool:
    config = _read_settings()
    hooks = config.get("hooks", {})
    removed = False
    for event in list(hooks.keys()):
        if isinstance(hooks[event], dict) and hooks[event].get(MARKER):
            del hooks[event]
            removed = True
    if removed:
        _write_settings(config)
    return removed


def _read_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_settings(data: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SETTINGS_PATH)
