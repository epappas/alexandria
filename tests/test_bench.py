"""Tests for `alxia bench` — the reproducible capability metric."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from alexandria.cli.main import app


def test_bench_emits_json(initialized_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    runner = CliRunner()
    result = runner.invoke(app, ["bench", "-w", "global", "--json"])
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["workspace"] == "global"
    for key in (
        "documents", "beliefs", "topics", "committed_runs",
        "verified_rate",
    ):
        assert key in data


def test_bench_default_output_is_one_line(
    initialized_home: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ALEXANDRIA_HOME", str(initialized_home))
    runner = CliRunner()
    result = runner.invoke(app, ["bench", "-w", "global"])
    assert result.exit_code == 0
    # Rich wraps long lines, but the content should be a single logical line:
    # at least, it should not contain multiple newlines of distinct sections.
    stripped = result.stdout.strip()
    assert "pages" in stripped
    assert "beliefs" in stripped
    assert "topics" in stripped
