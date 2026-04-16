"""Tests for the crash dump handler against the real filesystem."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from alexandria.core.crash_dump import crashes_dir, install_crash_handler, write_crash_dump


def test_write_crash_dump_creates_file(tmp_path: Path) -> None:
    home = tmp_path / "alexandria"
    try:
        raise ValueError("oh no")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        assert exc_type is not None and exc_value is not None
        path = write_crash_dump(home, exc_type, exc_value, exc_tb)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["exception_type"] == "builtins.ValueError"
    assert payload["exception_message"] == "oh no"
    assert payload["pid"] > 0
    assert "traceback" in payload


def test_install_crash_handler_replaces_excepthook(tmp_path: Path) -> None:
    """Installing the handler should change ``sys.excepthook`` and dump on call."""
    home = tmp_path / "alexandria"
    original = sys.excepthook
    try:
        install_crash_handler(home)
        assert sys.excepthook is not original
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None and exc_value is not None
            sys.excepthook(exc_type, exc_value, exc_tb)
        files = list(crashes_dir(home).glob("*.json"))
        assert len(files) >= 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["exception_type"] == "builtins.RuntimeError"
        assert payload["exception_message"] == "boom"
    finally:
        sys.excepthook = original
