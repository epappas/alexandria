"""``alexandria doctor`` — pass/fail health checks with actionable remediation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from alexandria.config import config_path, resolve_home
from alexandria.core.fts_integrity import check_fts_integrity
from alexandria.db.connection import connect, db_path
from alexandria.db.migrator import Migrator, MigratorError

console = Console()


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    remediation: str | None = None


def doctor_command() -> None:
    """Run a sequence of health checks and print pass/fail per check."""
    home = resolve_home()
    checks: list[CheckResult] = []

    checks.append(_check_home(home))
    if home.exists():
        checks.append(_check_config(home))
        checks.append(_check_database(home))
        checks.append(_check_migrations(home))
        checks.append(_check_fts(home))
        checks.append(_check_subdirs(home))

    fail_count = sum(1 for c in checks if not c.ok)

    for c in checks:
        marker = "[green][OK][/green]" if c.ok else "[red][FAIL][/red]"
        console.print(f"{marker} {c.name}")
        if c.detail:
            console.print(f"       [dim]{c.detail}[/dim]")
        if c.remediation:
            console.print(f"       [yellow]→ {c.remediation}[/yellow]")

    console.print()
    if fail_count == 0:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print(f"[red]{fail_count} check(s) failed.[/red]")
        raise typer.Exit(code=1)


def _check_home(home: Path) -> CheckResult:
    if home.exists() and home.is_dir():
        return CheckResult("alexandria home directory exists", True, str(home))
    return CheckResult(
        "alexandria home directory exists",
        False,
        f"missing: {home}",
        "run: alexandria init",
    )


def _check_config(home: Path) -> CheckResult:
    cfg = config_path(home)
    if cfg.exists():
        return CheckResult("config.toml present", True, str(cfg))
    return CheckResult(
        "config.toml present",
        False,
        f"missing: {cfg}",
        "run: alexandria init",
    )


def _check_database(home: Path) -> CheckResult:
    db = db_path(home)
    if db.exists():
        return CheckResult("SQLite database present", True, str(db))
    return CheckResult(
        "SQLite database present",
        False,
        f"missing: {db}",
        "run: alexandria init",
    )


def _check_migrations(home: Path) -> CheckResult:
    if not db_path(home).exists():
        return CheckResult("schema migrations applied", False, "no database", "run: alexandria init")
    migrator = Migrator()
    try:
        with connect(db_path(home)) as conn:
            migrator.verify_no_tampering(conn)
            current = migrator.current_version(conn)
            pending = migrator.pending(conn)
        if pending:
            return CheckResult(
                "schema migrations applied",
                False,
                f"{len(pending)} pending",
                "run: alexandria db migrate",
            )
        return CheckResult(
            "schema migrations applied",
            True,
            f"version {current}",
        )
    except MigratorError as exc:
        return CheckResult(
            "schema migrations applied",
            False,
            f"tamper detected: {exc}",
            "investigate alexandria/db/migrations/ for unauthorised edits",
        )


def _check_fts(home: Path) -> CheckResult:
    if not db_path(home).exists():
        return CheckResult("FTS5 integrity", False, "no database", "run: alexandria init")
    with connect(db_path(home)) as conn:
        report = check_fts_integrity(conn)
    if report.status == "ok":
        return CheckResult(
            "FTS5 integrity",
            True,
            f"{report.content_rows} rows in documents and documents_fts match",
        )
    return CheckResult(
        "FTS5 integrity",
        False,
        f"{report.status}: {report.error_message}",
        "run: alexandria reindex --fts-rebuild",
    )


def _check_subdirs(home: Path) -> CheckResult:
    expected = ["workspaces", "logs", "crashes", "backups", "secrets"]
    missing = [d for d in expected if not (home / d).exists()]
    if missing:
        return CheckResult(
            "expected subdirectories present",
            False,
            f"missing: {', '.join(missing)}",
            "run: alexandria init --force",
        )
    return CheckResult("expected subdirectories present", True, "")
