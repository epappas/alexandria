"""Sync orchestrator for source adapters.

Runs the sync cycle for one or all configured sources, coordinating
the adapter, rate limiter, circuit breaker, event storage, and runs table.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alexandria.core.adapters.events import insert_event
from alexandria.core.adapters.source_repository import (
    SourceConfig,
    complete_source_run,
    create_source_run,
    get_source,
    list_sources,
    sweep_orphaned_source_runs,
)
from alexandria.core.circuit_breaker import CircuitBreakerRegistry, CircuitOpenError
from alexandria.core.ratelimit import RateLimiter
from alexandria.core.runs import Run, generate_run_id, insert_run_row, update_run_row


@dataclass
class SyncReport:
    """Aggregated report across all source syncs."""

    sources_attempted: int = 0
    sources_succeeded: int = 0
    total_items: int = 0
    total_errors: int = 0
    per_source: list[dict[str, Any]] = field(default_factory=list)


def run_sync(
    conn: sqlite3.Connection,
    home: Path,
    workspace: str,
    workspace_path: Path,
    source_id: str | None = None,
    rate_limiter: RateLimiter | None = None,
    circuit_breakers: CircuitBreakerRegistry | None = None,
    secret_resolver: Any = None,
) -> SyncReport:
    """Execute sync for configured sources.

    1. Sweep orphaned source_runs
    2. For each enabled source: run adapter.sync(), store events, track runs
    """
    report = SyncReport()

    # Orphan sweep (amendment I3)
    sweep_orphaned_source_runs(conn)

    # Create a parent run row for this sync cycle
    run_id = generate_run_id()
    run = Run(
        run_id=run_id,
        workspace=workspace,
        triggered_by="cli:sync",
        run_type="sync",
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        insert_run_row(conn, run)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Determine which sources to sync
    if source_id:
        src = get_source(conn, source_id)
        if src is None:
            raise ValueError(f"source {source_id!r} not found")
        sources = [src]
    else:
        sources = list_sources(conn, workspace, enabled_only=True)

    for src in sources:
        report.sources_attempted += 1
        source_report = _sync_one_source(
            conn=conn,
            src=src,
            workspace=workspace,
            workspace_path=workspace_path,
            run_id=run_id,
            rate_limiter=rate_limiter,
            circuit_breakers=circuit_breakers,
            secret_resolver=secret_resolver,
        )
        report.per_source.append(source_report)
        report.total_items += source_report.get("items_synced", 0)
        report.total_errors += source_report.get("items_errored", 0)
        if source_report.get("items_errored", 0) == 0:
            report.sources_succeeded += 1

    # Update parent run
    conn.execute("BEGIN IMMEDIATE")
    try:
        update_run_row(
            conn, run_id,
            status="committed" if report.total_errors == 0 else "rejected",
            ended_at=datetime.now(UTC).isoformat(),
            verdict="pass" if report.total_errors == 0 else "partial",
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return report


def _sync_one_source(
    conn: sqlite3.Connection,
    src: SourceConfig,
    workspace: str,
    workspace_path: Path,
    run_id: str,
    rate_limiter: RateLimiter | None,
    circuit_breakers: CircuitBreakerRegistry | None,
    secret_resolver: Any,
) -> dict[str, Any]:
    """Sync a single source. Returns a per-source report dict."""
    from alexandria.core.adapters.git_local import GitLocalAdapter
    from alexandria.core.adapters.github_api import GitHubAdapter
    from alexandria.core.adapters.local import LocalAdapter

    # Circuit breaker check
    if circuit_breakers:
        cb = circuit_breakers.get(src.source_id)
        try:
            cb.check()
        except CircuitOpenError as exc:
            return {
                "source_id": src.source_id,
                "name": src.name,
                "status": "skipped",
                "reason": str(exc),
                "items_synced": 0,
                "items_errored": 0,
            }

    # Rate limit
    if rate_limiter and src.adapter_type in rate_limiter.registered():
        if not rate_limiter.acquire(src.adapter_type, timeout=10.0):
            return {
                "source_id": src.source_id,
                "name": src.name,
                "status": "rate_limited",
                "items_synced": 0,
                "items_errored": 0,
            }

    # Create source_run tracking row
    conn.execute("BEGIN IMMEDIATE")
    try:
        srun_id = create_source_run(conn, src.source_id, run_id=run_id)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Resolve adapter
    config = dict(src.config_json)
    if src.adapter_type == "github" and secret_resolver and "token_ref" in config:
        config["token"] = secret_resolver.resolve(config["token_ref"])

    adapter_map = {
        "local": LocalAdapter,
        "git-local": GitLocalAdapter,
        "github": GitHubAdapter,
    }
    adapter_cls = adapter_map.get(src.adapter_type)
    if adapter_cls is None:
        return {
            "source_id": src.source_id,
            "name": src.name,
            "status": "error",
            "reason": f"unknown adapter type: {src.adapter_type}",
            "items_synced": 0,
            "items_errored": 1,
        }

    adapter = adapter_cls() if src.adapter_type != "github" else adapter_cls(token=config.get("token"))

    try:
        items, sync_result = adapter.sync(workspace_path, config)
    except Exception as exc:
        if circuit_breakers:
            circuit_breakers.get(src.source_id).record_failure()
        conn.execute("BEGIN IMMEDIATE")
        try:
            complete_source_run(conn, srun_id, 0, 1, str(exc))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
        return {
            "source_id": src.source_id,
            "name": src.name,
            "status": "error",
            "reason": str(exc),
            "items_synced": 0,
            "items_errored": 1,
        }

    # Store events
    conn.execute("BEGIN IMMEDIATE")
    try:
        for item in items:
            insert_event(conn, workspace, src.source_id, item)
        complete_source_run(
            conn, srun_id, sync_result.items_synced, sync_result.items_errored,
            "; ".join(sync_result.errors) if sync_result.errors else None,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    if circuit_breakers:
        if sync_result.items_errored == 0:
            circuit_breakers.get(src.source_id).record_success()
        else:
            circuit_breakers.get(src.source_id).record_failure()

    return {
        "source_id": src.source_id,
        "name": src.name,
        "status": "completed",
        "items_synced": sync_result.items_synced,
        "items_errored": sync_result.items_errored,
        "errors": sync_result.errors,
    }
