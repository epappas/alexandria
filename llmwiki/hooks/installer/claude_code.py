"""Hook installer for Claude Code.

Writes hook entries to ~/.claude/settings.local.json with
_llmwiki_managed marker for clean uninstall.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

HOOK_PROTOCOL_VERSION = 1
SETTINGS_PATH = Path.home() / ".claude" / "settings.local.json"
MARKER = "_llmwiki_managed"


def install_claude_code_hooks(workspace: str | None = None) -> dict[str, Any]:
    """Install Stop + PreCompact hooks for Claude Code.

    Returns a dict with install status and paths.
    """
    llmwiki_bin = _find_bin()
    base_cmd = f"{llmwiki_bin} capture conversation --client claude-code --detach"
    if workspace:
        base_cmd += f" --workspace {workspace}"

    hooks = {
        "Stop": {
            "command": base_cmd,
            MARKER: True,
            "_protocol_version": HOOK_PROTOCOL_VERSION,
        },
        "PreCompact": {
            "command": f"{base_cmd} --reason pre-compact",
            MARKER: True,
            "_protocol_version": HOOK_PROTOCOL_VERSION,
        },
    }

    config = _read_settings()
    if "hooks" not in config:
        config["hooks"] = {}

    for event, hook_entry in hooks.items():
        config["hooks"][event] = hook_entry

    _write_settings(config)

    return {
        "client": "claude-code",
        "settings_path": str(SETTINGS_PATH),
        "hooks_installed": list(hooks.keys()),
        "protocol_version": HOOK_PROTOCOL_VERSION,
    }


def uninstall_claude_code_hooks() -> bool:
    """Remove llmwiki-managed hooks from Claude Code settings."""
    config = _read_settings()
    hooks = config.get("hooks", {})
    removed = False

    for event in list(hooks.keys()):
        entry = hooks[event]
        if isinstance(entry, dict) and entry.get(MARKER):
            del hooks[event]
            removed = True

    if removed:
        _write_settings(config)
    return removed


def verify_claude_code_hooks() -> dict[str, Any]:
    """Check if hooks are correctly installed and version matches."""
    config = _read_settings()
    hooks = config.get("hooks", {})

    results: dict[str, Any] = {"installed": False, "hooks": {}, "issues": []}

    for event in ("Stop", "PreCompact"):
        entry = hooks.get(event)
        if not entry or not isinstance(entry, dict):
            results["issues"].append(f"{event} hook not found")
            continue

        if not entry.get(MARKER):
            results["issues"].append(f"{event} hook not managed by llmwiki")
            continue

        version = entry.get("_protocol_version", 0)
        if version != HOOK_PROTOCOL_VERSION:
            results["issues"].append(
                f"{event} hook version mismatch: installed={version}, current={HOOK_PROTOCOL_VERSION}"
            )

        results["hooks"][event] = {
            "command": entry.get("command", ""),
            "version": version,
            "managed": True,
        }

    results["installed"] = len(results["issues"]) == 0 and len(results["hooks"]) > 0
    return results


def _find_bin() -> str:
    found = shutil.which("llmwiki")
    return found or f"{sys.executable} -m llmwiki"


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
