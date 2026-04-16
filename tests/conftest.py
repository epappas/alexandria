"""Shared pytest fixtures.

All fixtures hit real dependencies (real SQLite, real filesystem, real
subprocess invocations). No mocks for external services.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from llmwiki.config import Config, GeneralConfig, StateConfig, save_config
from llmwiki.core.workspace import GLOBAL_SLUG, init_workspace
from llmwiki.db.connection import connect, db_path
from llmwiki.db.migrator import Migrator


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Provide an isolated llmwiki home rooted in a tempdir.

    Yields the home path. Sets ``LLMWIKI_HOME`` so any code that reads the env
    var resolves the same directory.
    """
    home = tmp_path / "llmwiki"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LLMWIKI_HOME", str(home))
    monkeypatch.delenv("LLMWIKI_WORKSPACE", raising=False)
    yield home


@pytest.fixture
def initialized_home(tmp_home: Path) -> Path:
    """A home that has had migrations applied and a global workspace created."""
    for sub in ("logs", "crashes", "backups", "secrets", "workspaces", ".trash"):
        (tmp_home / sub).mkdir(parents=True, exist_ok=True)

    with connect(db_path(tmp_home)) as conn:
        Migrator().apply_pending(conn)

    cfg = Config(
        general=GeneralConfig(data_dir=str(tmp_home)),
        state=StateConfig(current_workspace=GLOBAL_SLUG),
    )
    save_config(tmp_home, cfg)

    init_workspace(
        tmp_home,
        slug=GLOBAL_SLUG,
        name="Global",
        description="The user's general knowledge workspace.",
    )
    return tmp_home


@pytest.fixture
def llmwiki_bin(tmp_home: Path) -> list[str]:
    """Return the argv prefix for invoking the llmwiki CLI as a subprocess.

    Uses ``python -m llmwiki`` rather than the installed entry point so the
    test does not depend on ``pip install -e .`` having been run before pytest.
    """
    env = os.environ.copy()
    env["LLMWIKI_HOME"] = str(tmp_home)
    return [sys.executable, "-m", "llmwiki"]


def run_llmwiki(home: Path, *args: str, expect_exit: int = 0) -> subprocess.CompletedProcess[str]:
    """Helper for running the CLI as a subprocess against an isolated home."""
    env = os.environ.copy()
    env["LLMWIKI_HOME"] = str(home)
    env.pop("LLMWIKI_WORKSPACE", None)
    result = subprocess.run(
        [sys.executable, "-m", "llmwiki", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != expect_exit:
        raise AssertionError(
            f"llmwiki {' '.join(args)}\n"
            f"exit={result.returncode} (expected {expect_exit})\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result
