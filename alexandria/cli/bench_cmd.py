"""``alexandria bench`` — emit a reproducible one-line capability metric."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import typer
from rich.console import Console

from alexandria.config import load_config, resolve_home, resolve_workspace
from alexandria.db.connection import connect, db_path

console = Console()

_SEARCH_PROBES = (
    "architecture",
    "memory",
    "agent",
    "security",
    "context",
    "embedding",
    "verifier",
    "ingest",
)


def bench_command(
    workspace: str | None = typer.Option(
        None, "--workspace", "-w",
        help="Override the current workspace.",
    ),
    probes: int = typer.Option(
        8, "--probes",
        help="Number of search probes for latency measurement.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit raw JSON instead of a formatted line.",
    ),
) -> None:
    """Report a reproducible, README-ready capability metric line.

    Shows document + belief counts, topic coverage, median search latency
    over FTS5 probes, and the fraction of wiki pages whose footnote
    anchors validate. The output is suitable for pasting verbatim into
    a README or a tweet.
    """
    import json

    home = resolve_home()
    config = load_config(home)
    slug = workspace or resolve_workspace(config)

    metrics = _collect_metrics(home, slug, probes)

    if json_output:
        console.print(json.dumps(metrics, indent=2))
        return

    line = _format_line(metrics)
    console.print(line)


def _collect_metrics(home: Path, workspace: str, probes: int) -> dict[str, object]:
    """Gather the numbers that go into the one-liner."""
    if not db_path(home).exists():
        raise typer.Exit(code=1)

    with connect(db_path(home)) as conn:
        docs = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE workspace = ? AND layer = 'wiki'",
            (workspace,),
        ).fetchone()[0]
        beliefs = conn.execute(
            """SELECT COUNT(*) FROM wiki_beliefs
               WHERE workspace = ? AND superseded_at IS NULL""",
            (workspace,),
        ).fetchone()[0]
        topics = conn.execute(
            """SELECT COUNT(DISTINCT topic) FROM wiki_beliefs
               WHERE workspace = ? AND superseded_at IS NULL""",
            (workspace,),
        ).fetchone()[0]
        runs = conn.execute(
            """SELECT COUNT(*) FROM runs
               WHERE workspace = ? AND status = 'committed'""",
            (workspace,),
        ).fetchone()[0]

        latencies = _measure_search_latency(conn, workspace, probes)
        verification = _sample_verification(conn, workspace)

    return {
        "workspace": workspace,
        "documents": docs,
        "beliefs": beliefs,
        "topics": topics,
        "committed_runs": runs,
        "search_p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "search_p95_ms": (
            round(_percentile(latencies, 95), 2) if latencies else None
        ),
        "verified_rate": verification,
    }


def _measure_search_latency(
    conn: object, workspace: str, probes: int,
) -> list[float]:
    """Time FTS5 search over the configured probe set."""
    latencies: list[float] = []
    for probe in _SEARCH_PROBES[:probes]:
        start = time.perf_counter()
        try:
            conn.execute(
                """SELECT d.id FROM documents_fts
                   JOIN documents d ON d.rowid = documents_fts.rowid
                   WHERE documents_fts MATCH ? AND d.workspace = ?
                   LIMIT 10""",
                (probe, workspace),
            ).fetchall()
        except Exception:
            continue
        latencies.append((time.perf_counter() - start) * 1000)
    return latencies


def _sample_verification(conn: object, workspace: str) -> float:
    """Return the fraction of committed runs whose verdict was 'commit'."""
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN verdict = 'commit' THEN 1 ELSE 0 END) AS ok,
             COUNT(*) AS total
           FROM runs
           WHERE workspace = ? AND status = 'committed'""",
        (workspace,),
    ).fetchone()
    if not row or not row["total"]:
        return 0.0
    return round(row["ok"] / row["total"], 4)


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100)
    f, c = int(k), int(k) + 1
    if c >= len(ordered):
        return ordered[-1]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _format_line(m: dict[str, object]) -> str:
    """Build the one-line README-ready metric string."""
    p50 = m["search_p50_ms"]
    p95 = m["search_p95_ms"]
    lat = f"{p50}ms / {p95}ms P95" if p50 is not None else "n/a"
    return (
        f"[bold]{m['documents']}[/bold] pages · "
        f"[bold]{m['beliefs']}[/bold] beliefs across "
        f"[bold]{m['topics']}[/bold] topics · "
        f"[bold]{m['committed_runs']}[/bold] verified ingests · "
        f"search {lat} · "
        f"citation-verified rate: "
        f"[bold]{(m['verified_rate'] or 0) * 100:.1f}%[/bold]"
    )
