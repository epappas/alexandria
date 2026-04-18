"""Hook installer for Claude Code.

Writes hook entries to ~/.claude/settings.local.json with
_alexandria_managed marker for clean uninstall.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

HOOK_PROTOCOL_VERSION = 1
SETTINGS_PATH = Path.home() / ".claude" / "settings.local.json"
MARKER = "_alexandria_managed"


def install_claude_code_hooks(workspace: str | None = None) -> dict[str, Any]:
    """Install Stop + PreCompact hooks for Claude Code.

    Returns a dict with install status and paths.
    """
    alexandria_bin = _find_bin()
    base_cmd = f"{alexandria_bin} capture conversation --client claude-code --detach"
    if workspace:
        base_cmd += f" --workspace {workspace}"

    # Claude Code hooks format: event -> array of {matcher, hooks[]}
    hook_entries = {
        "Stop": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": base_cmd}],
            MARKER: True,
        }],
        "PreCompact": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": f"{base_cmd} --reason pre-compact"}],
            MARKER: True,
        }],
    }

    config = _read_settings()
    if "hooks" not in config:
        config["hooks"] = {}

    for event, entries in hook_entries.items():
        existing = config["hooks"].get(event, [])
        if not isinstance(existing, list):
            existing = []
        # Remove any previous alexandria-managed entries
        existing = [e for e in existing if not (isinstance(e, dict) and e.get(MARKER))]
        existing.extend(entries)
        config["hooks"][event] = existing

    _write_settings(config)

    return {
        "client": "claude-code",
        "settings_path": str(SETTINGS_PATH),
        "hooks_installed": list(hook_entries.keys()),
        "protocol_version": HOOK_PROTOCOL_VERSION,
    }


def uninstall_claude_code_hooks() -> bool:
    """Remove alexandria-managed hooks from Claude Code settings."""
    config = _read_settings()
    hooks = config.get("hooks", {})
    removed = False

    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        filtered = [e for e in entries if not (isinstance(e, dict) and e.get(MARKER))]
        if len(filtered) < len(entries):
            removed = True
            hooks[event] = filtered if filtered else []

    if removed:
        _write_settings(config)
    return removed


def verify_claude_code_hooks() -> dict[str, Any]:
    """Check if hooks are correctly installed."""
    config = _read_settings()
    hooks = config.get("hooks", {})

    results: dict[str, Any] = {"installed": False, "hooks": {}, "issues": []}

    for event in ("Stop", "PreCompact"):
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            results["issues"].append(f"{event} hook has wrong format")
            continue

        managed = [e for e in entries if isinstance(e, dict) and e.get(MARKER)]
        if not managed:
            results["issues"].append(f"{event} hook not found")
            continue

        entry = managed[0]
        hook_cmds = entry.get("hooks", [])
        cmd = hook_cmds[0].get("command", "") if hook_cmds else ""
        results["hooks"][event] = {"command": cmd, "managed": True}

    results["installed"] = len(results["issues"]) == 0 and len(results["hooks"]) > 0
    return results


def _find_bin() -> str:
    found = shutil.which("alexandria")
    return found or f"{sys.executable} -m alexandria"


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
