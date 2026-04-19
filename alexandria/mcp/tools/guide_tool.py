"""``guide`` — L0/L1 tiered orientation for the connected agent.

Per ``04_guardian_agent.md``, the guide returns:
- **L0** (identity, ≤500 output tokens): workspace contract + identity + core schema rules.
- **L1** (essential state, ≤1500 output tokens): wiki counts, overview body, index top,
  last 15 log entries, pending queues, self-awareness summary, eval health.

Phase 1 ships L0 fully and L1 with ``not_yet_populated`` markers for runs,
verifier, and eval (those arrive in Phase 2+).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from alexandria.mcp.tools import WorkspaceResolver


def register(mcp: FastMCP, resolve: WorkspaceResolver) -> None:

    @mcp.tool(
        name="guide",
        description=(
            "Orient yourself in this workspace. Returns L0 (identity + contract, "
            "≤500 tokens) and L1 (essential state, ≤1500 tokens). Call this first "
            "every session. Stable prefix designed for prompt caching."
        ),
    )
    def guide(workspace: str | None = None) -> str:
        ws_path, slug = resolve(workspace)
        parts: list[str] = []

        # -- L0: Identity + contract ------------------------------------------
        parts.append("## L0 — Identity\n")

        identity_path = ws_path / "identity.md"
        if identity_path.exists():
            identity_text = identity_path.read_text(encoding="utf-8")[:2000]
            parts.append(identity_text.strip())
        else:
            parts.append(f"Workspace: **{slug}**")

        skill_path = ws_path / "SKILL.md"
        if skill_path.exists():
            skill_text = skill_path.read_text(encoding="utf-8")[:2000]
            parts.append("\n" + skill_text.strip())

        parts.append("\n---\n")

        # -- L1: Essential state -----------------------------------------------
        parts.append("## L1 — Essential State\n")

        # Wiki counts
        raw_count = _count_files(ws_path / "raw")
        wiki_count = _count_files(ws_path / "wiki")
        parts.append(f"- Raw sources: {raw_count}")
        parts.append(f"- Wiki pages: {wiki_count}")

        # Overview body (capped at ~600 tokens ≈ 2400 chars)
        overview_path = ws_path / "wiki" / "overview.md"
        if overview_path.exists():
            overview_text = overview_path.read_text(encoding="utf-8")[:2400]
            parts.append(f"\n### Overview\n{overview_text.strip()}")

        # Index top sections
        index_path = ws_path / "wiki" / "index.md"
        if index_path.exists():
            index_text = index_path.read_text(encoding="utf-8")[:1600]
            parts.append(f"\n### Index\n{index_text.strip()}")

        # Log entries (last 15) — read from wiki/log.md since wiki_log_entries
        # only gets populated in Phase 2+
        log_path = ws_path / "wiki" / "log.md"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8")
            log_lines = log_text.strip().split("\n")
            recent = log_lines[-45:]  # ~3 lines per entry × 15
            parts.append("\n### Recent log\n" + "\n".join(recent))
        else:
            parts.append("\n### Recent log\nNo log entries yet.")

        # Live state from database
        from alexandria.config import resolve_home
        from alexandria.db.connection import connect, db_path

        home = resolve_home()
        if db_path(home).exists():
            with connect(db_path(home)) as conn:
                runs = conn.execute("SELECT COUNT(*) as c FROM runs").fetchone()
                committed = conn.execute("SELECT COUNT(*) as c FROM runs WHERE status='committed'").fetchone()
                beliefs = conn.execute("SELECT COUNT(*) as c FROM wiki_beliefs WHERE workspace=? AND superseded_at IS NULL", (slug,)).fetchone()
                events = conn.execute("SELECT COUNT(*) as c FROM events WHERE workspace=?", (slug,)).fetchone()
                sources = conn.execute("SELECT COUNT(*) as c FROM source_adapters WHERE workspace=?", (slug,)).fetchone()

                parts.append(f"\n### Runs and verifier\n{runs['c']} runs ({committed['c']} committed)")
                parts.append(f"\n### Beliefs\n{beliefs['c']} current beliefs")
                parts.append(f"\n### Events and sources\n{events['c']} events, {sources['c']} source adapters")

                # Eval health
                try:
                    evals = conn.execute("SELECT metric, score, passed FROM eval_runs WHERE workspace=? ORDER BY started_at DESC LIMIT 5", (slug,)).fetchall()
                    if evals:
                        parts.append("\n### Eval health")
                        for ev in evals:
                            status = "PASS" if ev["passed"] else "FAIL"
                            parts.append(f"- {ev['metric']}: {ev['score']:.2f} ({status})")
                    else:
                        parts.append("\n### Eval health\nNo eval runs yet. Run `alxia eval run`.")
                except Exception:
                    parts.append("\n### Eval health\nRun `alxia eval run` to check quality.")

        parts.append(f"\n---\nworkspace: {slug}")

        return "\n".join(parts)


def _count_files(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(1 for f in directory.rglob("*") if f.is_file() and f.name != ".gitkeep")
