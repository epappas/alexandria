# alexandria — Implementation Plan

> **Status:** Draft v1, awaiting first-checkpoint review by `llm-architect`, `ai-engineer`, `mlops-engineer`.
>
> **Binding constraints (NON-NEGOTIABLE — these come from the user):**
> 1. **No fakes.** No `# TODO`, no `pass  # implement later`, no mock returning `success`, no stubbed function returning a hard-coded value, no placeholder `raise NotImplementedError`. Every commit produces real working code that solves a real problem.
> 2. **No lies.** Every claim in this plan, every status note in commits, every test result must be truthful. A failing test is a failing test; a partial feature is documented as partial.
> 3. **DRY / SOLID / KISS** apply to every line. Repeated logic gets extracted; classes have single responsibilities; abstractions exist only where they earn their keep; complexity is rejected by default.
> 4. **Tests hit real dependencies.** Real SQLite, real Anthropic API (with a small budget), real GitHub API (against a small public repo), real RSS feeds, real filesystem. No recorded-response harnesses for the integration suite. Unit tests can use in-memory variants of the same real components (in-memory SQLite, recorded-tape only when a recorded tape is honest about what it is).
> 5. **Every phase produces a demoable end-to-end system.** A user can install whatever has been shipped through phase N, follow a documented workflow, and have something working that they can use immediately. No phase ends in a state that requires the next phase to be useful.
> 6. **Every phase ends with a three-agent review** (`llm-architect`, `ai-engineer`, `mlops-engineer`) of the actual code, tests, and demo — not of intentions.

This plan defines **13 sequential phases** that take alexandria from empty repository to v1.0.0 release. Each phase is sized to be small enough to ship cleanly but large enough to deliver real user value. Phase boundaries are chosen so that a phase failure (e.g., a critical reviewer finding) blocks only that phase's work, never invalidates a prior phase.

## Architecture references

This plan implements the architecture defined in `docs/architecture/01_*.md` through `docs/architecture/20_cli_surface.md`. Key docs to keep open during implementation:

- `01_vision_and_principles.md` — the 20 invariants. Every PR must respect them.
- `13_hostile_verifier.md` — the staged-write transaction. Phase 2 implements this; every subsequent phase respects it.
- `14_evaluation_scaffold.md` — the freeze clause. New sources are blocked once we have shipped enough that M1/M2 must run.
- `20_cli_surface.md` — the binding CLI contract. Every command implemented must produce the help text in this doc.

## Cross-cutting principles

These apply across all phases.

### Code organization

- **Package layout:**
  ```
  alexandria/
  ├── __init__.py
  ├── __main__.py              # python -m alexandria entry point
  ├── cli/                      # Typer command groups, one file per group
  │   ├── __init__.py
  │   ├── main.py
  │   ├── workspace.py
  │   ├── source.py
  │   ├── ingest.py
  │   ├── why.py
  │   ├── eval.py
  │   ├── runs.py
  │   ├── status.py
  │   ├── ...
  │   └── mcp.py
  ├── core/                     # the engine; no CLI / MCP / daemon coupling
  │   ├── workspace.py          # Workspace, WorkspaceConfig
  │   ├── runs.py               # Run state machine, staged transaction
  │   ├── verifier/             # Verifier protocol + default implementation
  │   ├── beliefs/              # Belief extraction, sidecar IO, query
  │   ├── cascade/              # stage_merge, stage_hedge, stage_new_page, stage_cross_ref
  │   ├── citations/            # quote anchor hashing + verification
  │   └── search/               # FTS5 wrappers, grep, list
  ├── adapters/                 # source adapters, all SourceAdapter protocol
  │   ├── base.py               # SourceAdapter protocol
  │   ├── local.py
  │   ├── github_api.py
  │   ├── git_local.py
  │   ├── rss.py
  │   ├── imap_newsletter.py
  │   ├── ...
  │   └── conversation.py
  ├── mcp/                      # FastMCP server + tool implementations
  │   ├── server.py
  │   ├── tools/                # one file per tool: guide, list, grep, search, ...
  │   └── transport.py
  ├── daemon/                   # supervised-subprocess parent + children
  │   ├── parent.py
  │   ├── scheduler.py
  │   ├── workers/
  │   ├── webhook_recv.py
  │   └── ipc.py
  ├── db/                       # SQLite layer
  │   ├── connection.py         # ScopedDB + WAL config
  │   ├── migrations/           # numbered SQL files
  │   │   ├── 0001_initial.sql
  │   │   ├── 0002_*.sql
  │   │   └── ...
  │   └── migrator.py
  ├── llm/                      # LLMProvider abstraction
  │   ├── base.py
  │   ├── anthropic.py
  │   ├── openai.py
  │   ├── openai_compat.py
  │   └── budget.py
  ├── secrets/                  # vault + audit log
  │   ├── vault.py
  │   ├── resolver.py
  │   ├── redactor.py
  │   └── audit.py
  ├── observability/            # logs + status + doctor + run_id correlation
  │   ├── logger.py
  │   ├── status.py
  │   └── doctor.py
  ├── eval/                     # M1-M5 implementations
  │   ├── base.py
  │   ├── m1_citation_fidelity.py
  │   ├── m2_cascade_coverage.py
  │   ├── m3_retroactive_query.py
  │   ├── m4_cost.py
  │   └── m5_self_consistency.py
  ├── hooks/                    # client hook scripts + installer
  │   ├── installer/
  │   └── scripts/
  └── config.py                 # config.toml loader + validation
  ```
- **One concern per file.** When a file exceeds 400 lines, refactor.
- **One responsibility per class.** When a class touches more than one of (storage, scheduling, LLM call, IO, validation), split it.
- **No god objects.** No `Workspace` class that owns SQLite + filesystem + verifier + cli + everything.
- **Imports are explicit.** No `from alexandria.core import *`. No re-exports for convenience.
- **Type hints everywhere.** `mypy --strict` clean. `Any` requires a comment justifying it.

### Test strategy

- **Three test tiers**, all real:
  1. **Unit tests** (`tests/unit/`) — fast, isolated, in-memory dependencies that are themselves real (`sqlite3:///:memory:`, in-memory filesystem via real `tempfile.TemporaryDirectory`). Run on every commit.
  2. **Integration tests** (`tests/integration/`) — real Postgres-equivalent (real SQLite file on disk in a temp dir), real subprocess calls, real git operations against a real local repo. Run on every PR.
  3. **End-to-end tests** (`tests/e2e/`) — real Anthropic API (small budget), real GitHub API (against a public test repo we control), real RSS fetches, real MCP protocol roundtrips with a real client subprocess. Run on the main branch + nightly.
- **No mocks for external services.** If the test needs an LLM call, it makes a real LLM call against a small budget. If the test needs a GitHub fetch, it hits the real GitHub API. The cost of running the e2e suite is part of the project's operational budget, not a reason to fake.
- **Recorded tapes are allowed only with disclosure.** When a tape is used (because a real call would be too slow or too expensive for the inner test loop), the tape file is committed alongside the test, the recording date is in the file header, and a corresponding e2e test exists that re-runs the real call on a slower cadence. The tape must be re-recorded when it expires.
- **Test names match behavior, not implementation.** `test_ingest_with_fabricated_citation_is_rejected` not `test_verifier_returns_false`.
- **Coverage target: 85%.** Not for vanity — coverage gaps are where bugs hide. Lower is allowed only with a comment explaining why.

### Database discipline

- **Every schema change is a numbered migration file** in `alexandria/db/migrations/`. No exceptions.
- **Migrations are immutable once applied to main.** A bug in an applied migration is fixed by a new migration that corrects it.
- **Every migration is tested**: a test creates a fresh DB, runs migrations 0001 → N, and asserts the resulting schema matches the expected shape. A migration that fails this test cannot merge.
- **`PRAGMA user_version`** is the single source of truth for current schema version.
- **`PRAGMA journal_mode = WAL`** on every connection.

### CLI discipline

- **Every command in `20_cli_surface.md` exists** by the end of its phase. A command without a working implementation must not appear in `alexandria -h` (and therefore must not appear in the help spec for that phase).
- **`-h` / `--help` work everywhere**, including unimplemented sub-commands when the parent command is implemented (the unimplemented sub-command prints a clear `not yet shipped — planned for phase N` message and exits with code 2). This is the **only** exception to the "no placeholders" rule, and it is allowed only because the user needs `-h` discovery to work end-to-end.
- **Exit codes:** 0 success, 1 user error, 2 system error or not-yet-shipped, 3 quota / budget / circuit-breaker tripped.
- **`--json` output** wherever applicable, with a stable schema documented in the relevant architecture doc.
- **Idempotent operations** (e.g., `init`, `mcp install`, `source add` with same config) are no-ops on re-run, never errors.

### Logging and observability discipline

- **Every operation produces logs in JSONL format** under `~/.alexandria/logs/`, organized into the seven log families defined in `17_observability.md`.
- **Every operation has a `run_id`** that correlates across log families.
- **No print statements outside the CLI's user-facing output layer.** Diagnostic logs go to the log files; the CLI prints structured human or JSON output to stdout.

### LLM call discipline

- **Every LLM call is wrapped by the `LLMProvider` abstraction** from `11_inference_endpoint.md`. No direct `anthropic.Anthropic().messages.create()` calls outside the provider implementations.
- **Every LLM call carries a `run_id`** for correlation.
- **Every LLM call records cost** to `llm-usage-YYYY-MM-DD.jsonl`.
- **Every LLM call respects the per-operation budget cap** from `[llm.budgets]`.
- **The hostile verifier from doc 13 is non-negotiable** for every wiki write from Phase 2 onward. There is no `--no-verify` shortcut except as documented in doc 13 (rare, audit-logged, requires `--reason`).

---

## Phase 0 — Foundation (~1 week)

**Goal:** the binary exists, init works, basic workspace management works, schema migration framework is in place.

### Deliverables

1. **Project skeleton**
   - `pyproject.toml` with Typer, pydantic, aiosqlite, sqlite-utils, ruff, mypy, pytest, pytest-asyncio
   - `python -m alexandria` and `alexandria` console script entry points
   - Pre-commit hooks: `ruff check`, `ruff format --check`, `mypy --strict`

2. **CLI scaffold (Typer)**
   - `alexandria -h` produces the canonical help from `20_cli_surface.md`. Commands implemented in this phase are functional; commands not yet shipped print `not yet shipped — planned for phase N` and exit code 2.
   - `alexandria --version` prints version from `alexandria/__init__.py:__version__`.

3. **Config loading**
   - `config.py`: parses `~/.alexandria/config.toml` with pydantic models. Default values match `01_vision_and_principles.md`.
   - `ALEXANDRIA_HOME`, `ALEXANDRIA_WORKSPACE` env var overrides.

4. **SQLite + migration framework** (from `16_operations_and_reliability.md`)
   - `db/connection.py`: WAL mode connection wrapper.
   - `db/migrator.py`: reads `db/migrations/*.sql` in order, checks `schema_migrations` table + `PRAGMA user_version`, applies pending, takes auto-backup before each.
   - `db/migrations/0001_initial.sql`: creates `workspaces`, `documents`, `documents_fts`, `schema_migrations`, `daemon_heartbeats` tables.
   - `alexandria db migrate` and `alexandria db status` commands.
   - Tests: fresh DB → migrate to head → verify schema; corrupt migration file → migrate fails cleanly.

5. **Workspace primitives** (from `03_workspaces_and_scopes.md`)
   - `core/workspace.py`: `Workspace` dataclass + `WorkspaceConfig`, `init_workspace`, `list_workspaces`, `resolve_workspace`.
   - On-disk layout: `~/.alexandria/workspaces/<slug>/{SKILL.md, identity.md, config.toml, raw/, wiki/}`.
   - SQLite row in `workspaces` table created on init.

6. **`alexandria init`** — creates `~/.alexandria/`, runs initial migration, creates the `global` workspace, writes default config.

7. **`alexandria workspace use <slug>`**, `workspace current`, `workspace list`.

8. **`alexandria project create <name>`**, `project list`, `project info <name>`, `project rename`, `project delete` (soft delete to `~/.alexandria/.trash/`).

9. **`alexandria paste`** — reads stdin into `raw/local/<yyyy-mm-dd-slug>.md` with sha256 dedup against existing files.

10. **`alexandria status` (basic)** — daemon: not running; workspaces: list with counts; schema version; data dir.

### Tests
- Unit: every public function in `core/workspace.py`, `db/migrator.py`, `config.py`.
- Integration: full `init` → `project create` → `paste` → `status` flow against a real on-disk SQLite.
- E2E: `subprocess.run` of the binary in a tempdir, asserts on stdout.

### Demoable end state
A user runs `pip install -e .`, then `alexandria init`, then `alexandria project create research`, then `echo "test note" | alexandria paste --workspace research --title test`, then `alexandria status` and sees the workspace, the file, the schema version. Every command in the help that isn't implemented prints a clear "phase N" message — no surprise crashes.

### Phase exit criteria
- All tests green on a fresh checkout.
- `mypy --strict` clean.
- `ruff check` clean.
- A clean `pip install -e .` followed by the demo script above runs to completion with no errors.
- **Three-agent review passes.**

---

## Phase 1 — Read-only MCP server (~1.5 weeks)

**Goal:** Claude Code can connect to alexandria via stdio MCP and read the workspace.

### Deliverables

1. **FastMCP integration**
   - `mcp/server.py`: `FastMCP` instance, stdio transport, workspace binding (open + pinned modes from `08_mcp_integration.md`).
   - `alexandria mcp serve` command (open mode).
   - `alexandria mcp serve --workspace <slug>` (pinned mode).

2. **Read-only tools** from `04_guardian_agent.md`
   - `guide` (with L0/L1 tiered output, hard token budgets per `04_guardian_agent.md`)
   - `list` (glob over the document layer)
   - `grep` (subprocess to ripgrep against the workspace files)
   - `search` (FTS5 keyword over `documents_fts`)
   - `read` (single file or glob batch with character budget)
   - `follow` — read-only; quote anchors not yet stored, so this returns the linked raw file path without the deterministic hash check (the check arrives in Phase 2)
   - `history` — empty for now (no runs in Phase 1); returns an empty list
   - `overview` (cold-start silhouette tool from llm-architect's review)

3. **Tool registration discipline**
   - One file per tool under `mcp/tools/`.
   - Each tool implements a `Tool` protocol with `register(mcp)`, `name`, `description`.
   - The tool list in `mcp/tools/__init__.py` is the single registry.

4. **MCP installer** (`mcp install <client>`)
   - `hooks/installer/claude_code.py` — writes `~/.claude.json` or `.mcp.json` with the `_alexandria_managed: true` marker.
   - `alexandria mcp install claude-code` command.
   - `alexandria mcp install claude-desktop` (Mac path).

5. **MCP status** (`mcp status`) — lists running stdio sessions by parent PID.

### Tests
- Unit: each tool's pure logic (FTS5 query construction, glob handling, budget enforcement).
- Integration: spawn the MCP server in a subprocess, send real MCP protocol messages over stdio, assert correct responses. Use the real `mcp` package, not a fake.
- E2E: `claude mcp add alexandria -- alexandria mcp serve`; spawn `claude` subprocess (if available in CI) to run a single tool call; assert response. If `claude` binary is not in CI, use a small Python client implementing the MCP protocol against our server.

### Demoable end state
User runs `alexandria mcp install claude-code`, restarts Claude Code, types *"what's in my alexandria global workspace?"*, and Claude Code calls `guide` then `list` then `read` and reports back. No writes yet — read-only.

### Phase exit criteria
- All tests green.
- A real Claude Code session can connect, call every read-only tool, and get the right answer.
- `alexandria -h` shows the new commands as implemented.
- **Three-agent review passes.**

---

## Phase 2 — Hostile verifier and staged writes (~2.5 weeks)

**This is the load-bearing phase.** Every subsequent phase depends on the staged-write transaction working correctly.

**Goal:** wiki writes happen, but only through staged runs verified by an independent hostile verifier agent.

### Deliverables

1. **Runs table and state machine** (from `13_hostile_verifier.md`)
   - Migration `0002_add_runs_and_provenance.sql`: creates `runs`, extends `wiki_claim_provenance` with quote anchor columns, creates indexes.
   - `core/runs.py`: `Run`, `RunState`, `RunRepository` with the five-state state machine.
   - On-disk layout: `~/.alexandria/runs/<run_id>/{meta.json, plan.json, staged/, verifier/, status}`.

2. **Staged write helpers** (from `15_cascade_and_convergence.md`)
   - `core/cascade/`: `stage_merge`, `stage_hedge`, `stage_new_page`, `stage_cross_ref`.
   - `core/cascade/str_replace.py`: surgical exactly-one-match string replacement against staged files.
   - Convergence policy enforcement (the `::: disputed` marker shape).

3. **Verbatim quote anchors** (from `13_hostile_verifier.md` + `06_data_model.md`)
   - `core/citations/`: extract footnotes from a wiki page, locate the cited span in the raw source, compute sha256, store in `wiki_claim_provenance` with `source_quote`, `source_quote_hash`, `source_quote_offset`.
   - Deterministic verification: re-compute hash on demand and compare.

4. **Verifier protocol and default implementation** (from `13_hostile_verifier.md`)
   - `core/verifier/base.py`: `Verifier` protocol with one method `async def verify(run_id, workspace, plan, staged_dir) -> VerifierVerdict`.
   - `core/verifier/default.py`: default implementation that:
     - Spawns a fresh LLM session via `LLMProvider` (Phase 2 implements the Anthropic provider; full provider abstraction matures in Phase 8)
     - Runs read-only tools against the staged content
     - Performs deterministic check #3 (hash anchors) before any LLM call
     - Performs semantic check #4 (LLM vote per claim)
     - Returns `commit | reject | revise` with per-claim findings
   - Verifier loop: writer → stage → verifier → commit/reject/revise. Bounded at 3 loops (`MAX_LOOPS`).
   - Manual override: `alexandria verify override <run_id> --reason "..."`, audit-logged.

5. **`write` MCP tool** — staging-aware
   - `create`, `str_replace`, `append` operations all stage to `runs/<run_id>/staged/` first.
   - On staged-run completion, hand to verifier.
   - On `commit` verdict, atomically move staged → wiki/ via `git mv` + `git commit -m "alexandria run <run_id>"`.
   - Per-workspace `fcntl` advisory lock on the commit step.
   - On `reject` verdict, move staged → `failed/`, return reason.

6. **Daemon-startup orphan sweep** — minimal version: on every daemon start, transition `pending` / `verifying` runs to `abandoned`.

7. **`alexandria ingest <source>`** — basic, local files only. Accepts a markdown or text file, runs the cascade workflow against it.

8. **`alexandria runs show <run_id>`** — inspect a run: meta, verdict, staged diff, verifier transcript.

9. **`alexandria verify override <run_id>`** — audit-logged manual override.

10. **Anthropic LLM provider** (minimum viable) — used by the verifier and the writer in this phase. Full provider abstraction matures in Phase 8.
    - `llm/base.py`: `LLMProvider` protocol.
    - `llm/anthropic.py`: real `anthropic` SDK calls. Tool use. Cost tracking to `llm-usage.jsonl`.
    - `llm/budget.py`: per-operation budget enforcement.
    - Budget config: `[llm.budgets.ingest]`, `[llm.budgets.verifier]`.

### Tests

- Unit: every cascade stage helper, the run state machine, the citation extraction + hash check (deterministic, no LLM).
- Integration: write a markdown page with a fabricated citation → verifier rejects via the deterministic hash check (NO LLM call needed for this test, because the hash mismatch is caught before the LLM is invoked).
- Integration: write a markdown page with a real citation against a real raw source → deterministic check passes → semantic verifier vote succeeds (real Anthropic API call against a small budget) → run commits.
- Integration: write a cascade touching 5 pages → all 5 staged → verifier passes → all 5 commit atomically. Then test the failure case: artificially inject a multi-match `str_replace` failure → entire run rejects → live wiki untouched.
- E2E: from Claude Code via MCP, ask the agent to ingest a markdown file → verify the cascade runs → verify the wiki updates land → verify the runs table records the commit.

### Demoable end state
User runs `alexandria ingest research/docs/intro.md` (a real file in their workspace's raw layer). The guardian reads it, plans a cascade, stages the writes, the verifier checks every footnote against the raw source via deterministic hash, and on success commits to `wiki/`. The user can then `alexandria runs show <run_id>` to see exactly what happened. They can introduce a deliberate fabricated citation, run ingest again, and watch the verifier reject it with a structured reason.

### Phase exit criteria
- All tests green.
- A fabricated citation is **always** rejected without an LLM call (deterministic hash check).
- A multi-page cascade either commits all pages or none.
- The `runs` table is the source of truth for run state, and `runs show` returns it accurately.
- `alexandria -h` shows `ingest`, `runs show`, `verify override` as implemented.
- **Three-agent review passes.** This phase will get the most rigorous review because it is the load-bearing correctness mechanism.

---

## Phase 3 — Belief revision (~1.5 weeks)

**Goal:** every wiki write produces structured beliefs in `wiki_beliefs` + sidecar JSON; the `why` tool answers belief queries with full provenance.

### Deliverables

1. **`wiki_beliefs` table + sidecars** (from `06_data_model.md` + `19_belief_revision.md`)
   - Migration `0003_add_beliefs.sql`: creates `wiki_beliefs`, `wiki_beliefs_fts`.
   - On-disk format: `wiki/<topic>/<page>.beliefs.json` next to the markdown page, git-versioned.
   - `core/beliefs/sidecar.py`: read/write sidecar JSON.
   - `core/beliefs/repository.py`: SQLite operations on `wiki_beliefs`.

2. **Belief extraction by writer** (from `19_belief_revision.md`)
   - `core/beliefs/extractor.py`: parses a wiki page's body, identifies substantive claims, links to footnotes, optionally extracts subject/predicate/object.
   - The extractor runs as part of the staged-write workflow in Phase 2; this phase wires it in.
   - Each belief gets a `belief_id` (UUID).
   - Supersession detection: when a new belief on the same `(subject, predicate)` exists, mark the old one superseded.

3. **Verifier belief checks** — extend `core/verifier/default.py` with the four belief-specific checks (coverage, provenance link, supersession sanity, statement support) from `19_belief_revision.md`.

4. **`why` MCP tool and CLI**
   - `mcp/tools/why.py`: resolve query → SQL lookup → return current beliefs + history with provenance trail. The basic case is pure SQL; semantic re-validation is opt-in.
   - `alexandria why "<query>"` CLI command.
   - JSON output for scripting.

5. **`beliefs` CLI commands**
   - `alexandria beliefs list --topic <t>`
   - `alexandria beliefs history <belief_id>`
   - `alexandria beliefs verify` (re-runs hash check on every quote anchor)
   - `alexandria beliefs export --format json|csv`
   - `alexandria beliefs supersede <old> <new>` (manual)

6. **Reindex extension** — `alexandria reindex --rebuild-beliefs` walks `wiki/**/*.beliefs.json` and rebuilds `wiki_beliefs` from sidecars.

### Tests

- Unit: belief extractor on hand-crafted markdown fixtures, sidecar IO roundtrip, supersession detection.
- Integration: ingest source A introducing a claim → sidecar exists → `wiki_beliefs` has the row → `why "<topic>"` returns it. Then ingest source B contradicting source A → sidecar updated with both beliefs → SQL shows the supersession chain → `why` returns both.
- E2E via Claude Code: agent asks "why do we believe X" → MCP `why` tool returns the chain → agent renders it for the user.

### Demoable end state
User ingests two papers that disagree. They run `alexandria why "OAuth refresh endpoint"` and see both the current belief and the prior superseded belief, each with the verbatim source quote and a `verified_against_source: true` flag. They can then run `alexandria beliefs verify` to re-check every quote anchor against the live raw files.

### Phase exit criteria
- Every wiki write from Phase 2 onward now also produces beliefs.
- `why` returns deterministic, structured, provenance-backed answers.
- M1 (citation fidelity from `14_evaluation_scaffold.md`) becomes implementable on top of the belief layer in Phase 9.
- **Three-agent review passes.**

---

## Phase 4 — Source adapters: local + git-local + GitHub (~2.5 weeks)

**Goal:** ingest from real external sources (local filesystem, cloned git repos, GitHub API).

### Deliverables

1. **`SourceAdapter` protocol** (from `05_source_integrations.md`)
   - `adapters/base.py`: `SourceAdapter`, `SourceItem`, `FetchedDocument`, `AdapterKind` enum.

2. **`source_adapters` and `source_runs` tables**
   - Migration `0004_add_sources.sql`: creates both tables, adds indexes from `06_data_model.md`.
   - State machine for `source_runs` with daemon-startup orphan sweep.

3. **Local filesystem adapter** (`adapters/local.py`)
   - Walks a directory, returns files matching a glob, treats `.md`/`.txt`/`.pdf` as content sources.
   - PDF extraction via `pymupdf`.
   - Content hashing for incremental sync.

4. **Git-local adapter** (`adapters/git_local.py`) — the primary git path from `10_event_streams.md`
   - Clones a repo to `raw/git/<repo>/` on first sync.
   - Fetches on subsequent runs.
   - Extracts commits via `git log` into the `events` table (events table arrives in this phase via migration `0005_add_events.sql`).
   - Safelist of read-only git subcommands exposed via the `git_log`, `git_show`, `git_blame` MCP tools.

5. **GitHub API adapter** (`adapters/github_api.py`) — the layer-2 metadata path from `10_event_streams.md`
   - REST endpoints for issues, pulls, releases, discussions (NOT commits — git-local handles those).
   - Backfill track + live track.
   - Webhook receiver (Phase 6 wires this into the daemon).

6. **Rate limiter and circuit breakers** (from `16_operations_and_reliability.md`)
   - `core/ratelimit.py`: per-provider `TokenBucket`, `RateLimiter` instance shared across adapters.
   - `core/circuit_breaker.py`: per-adapter three-state breaker.
   - Configuration in `config.toml`.

7. **Secret vault** (from `18_secrets_and_hooks.md`) — minimum viable
   - `secrets/vault.py`: AES-256-GCM via `cryptography`, master key from OS keyring via `keyring` package.
   - `secrets/resolver.py`: cached resolver injected into adapters.
   - `ALEXANDRIA_VAULT_PASSPHRASE` env var fallback for headless servers.
   - `alexandria secrets set <ref>`, `secrets list`, `secrets verify <ref>`.
   - **Rotation, revocation, audit log come in Phase 11** to keep this phase focused.

8. **MCP tools added in this phase**
   - `events` (basic — covers git-local commits + github metadata events)
   - `timeline`
   - `git_log`, `git_show`, `git_blame`
   - `sources` (read-only adapter listing)

9. **CLI commands**
   - `alexandria source add <type> --workspace <slug>` (interactive prompts for config)
   - `alexandria source list`
   - `alexandria source remove <id>`
   - `alexandria sync [<source-id>]`

### Tests

- Unit: rate limiter token bucket math, circuit breaker state transitions, secret vault encrypt/decrypt roundtrip.
- Integration: clone a real local git repo (created in the test setup), run git-local sync, assert commits land in `events`. Run a real GitHub API fetch against a small public repo we control, assert issues/PRs land.
- E2E: full workflow — `source add github`, `sync`, `events`, ingest something based on the events.

### Demoable end state
User runs `alexandria source add github --workspace research`, enters their PAT (stored encrypted), enters the repo `acme/web-app`. Then `alexandria sync`. Then opens Claude Code and asks *"summarize the auth refactor PRs from the last week"* — Claude Code calls `events(workspace=research, source=github, refs_contains=auth, since=7d)`, gets the matching PRs, follows the refs to the related commits via `git_log`, synthesizes the answer.

### Phase exit criteria
- Real GitHub API hits work with rate limiting and circuit breakers.
- Real git clone + `git log` extraction populates events.
- The `eval` freeze clause from `14_evaluation_scaffold.md` is now active: from Phase 5 onward, new source adapters are blocked until M1+M2 ship in Phase 9.
- **Three-agent review passes.**

---

## Phase 5 — Subscriptions: RSS + IMAP newsletters (~1.5 weeks)

**Goal:** poll-based content adapters for blogs, Substack, and email newsletters.

### Deliverables

1. **RSS/Atom adapter** (`adapters/rss.py` from `09_subscriptions_and_feeds.md`)
   - `feedparser`-based with full content extraction from `<content:encoded>` / `<summary type="html">`.
   - Substack convenience wrapper (URL pattern).
   - Image download for archival integrity.

2. **IMAP newsletter adapter** (`adapters/imap_newsletter.py`)
   - IMAP IDLE where supported, polling otherwise.
   - Mail chrome stripping (unsubscribe links, tracking pixels, "view in browser").
   - Per-publication redaction rules.

3. **`subscriptions_queue` table**
   - Migration `0006_add_subscriptions.sql`.

4. **MCP `subscriptions` tool** — read-only listing of pending items.

5. **CLI commands**
   - `alexandria subscriptions list`
   - `alexandria subscriptions show <id>`
   - `alexandria subscriptions ingest [filter]`
   - `alexandria subscriptions dismiss <id>`
   - `alexandria subscriptions poll`

### Tests

- Unit: RSS feed parsing on real recorded feed XML, image URL extraction.
- Integration: real fetch against `https://simonwillison.net/atom/everything/` (verified working in `research/raw/` previously). Assert items land. Assert idempotent re-poll skips unchanged items via content hash.
- Integration: against a real IMAP test account (test fixture documented in test setup).
- E2E: full sub flow.

### Demoable end state
User runs `alexandria source add rss https://simonwillison.net/atom/everything/`, then `alexandria sync`. Then `alexandria subscriptions list` shows new items. They open Claude Code and ask *"summarize the new posts from this week"* — Claude Code calls `subscriptions` and `read`, synthesizes.

### Phase exit criteria
- Real RSS fetches work.
- Idempotent re-polls.
- **Three-agent review passes.**

---

## Phase 6 — Daemon and scheduling (~2.5 weeks)

**Goal:** the optional `alexandria daemon` runs scheduled syncs, polls subscriptions, hosts the MCP HTTP server, and produces structured logs with run_id correlation.

### Deliverables

1. **Supervised subprocess parent** (from `16_operations_and_reliability.md`)
   - `daemon/parent.py`: spawns and supervises children via `multiprocessing.Process`.
   - Restart policies per child.
   - IPC over Unix socket with a small JSON protocol.

2. **Children**
   - `daemon/scheduler.py`: `apscheduler` loop that picks the next job.
   - `daemon/workers/sync_worker.py`: drains the source-sync queue.
   - `daemon/workers/subscription_worker.py`: drains the subscriptions poll queue.
   - `daemon/mcp_http.py`: HTTP+SSE MCP server (in addition to stdio from Phase 1).
   - `daemon/webhook_recv.py`: HTTP listener for inbound webhooks.

3. **Heartbeats** — `daemon_heartbeats` table, 5-second writes, 45-second deadline.

4. **Orphaned-run sweep on startup** (full version from `16_operations_and_reliability.md`)
   - Sweeps `runs` and `source_runs`.

5. **Run ID correlation** (from `17_observability.md`)
   - Every log line has `run_id`, `workspace`, `layer`, `event`, `level`.
   - `observability/logger.py`: structured logger that emits to the right log family.

6. **`alexandria status --json`** — full operational dashboard (the JSON shape from `17_observability.md`).

7. **`alexandria doctor`** — health checks with actionable remediation.

8. **`alexandria logs show <run_id>`** — merged log view.

9. **CLI commands**
   - `alexandria daemon start | stop | status`
   - `alexandria status --json --watch`
   - `alexandria doctor`
   - `alexandria logs show <run_id>`

### Tests

- Unit: scheduler logic, IPC protocol, log emitter.
- Integration: spawn daemon in a subprocess, verify children start, verify scheduled job fires, kill a child, verify restart, assert orphan sweep on startup transitions stale runs.
- E2E: full daemon lifecycle with real adapters scheduled at 1-minute cadence; observe logs land; observe `alexandria status --json` reflects state; observe `doctor` reports health.

### Demoable end state
User runs `alexandria daemon start`. Behind the scenes, the scheduler polls their RSS feeds every 4 hours, syncs their git repos every 5 minutes, and the MCP HTTP server is reachable at `http://localhost:7219/mcp`. They can run `alexandria status` to see everything. They can `alexandria doctor` to validate.

### Phase exit criteria
- Daemon runs reliably for 24 hours continuous in CI.
- A killed child is restarted by the parent.
- Orphaned runs are swept on every startup.
- **Three-agent review passes.**

---

## Phase 7 — Conversation capture and hooks (~1.5 weeks)

**Goal:** every Claude Code session lands in the engine, and the MCP-side capture path also lands every tool call from any connected client.

### Deliverables

1. **Conversation adapter** (`adapters/conversation.py` from `12_conversation_capture.md`)
   - Format detector: Claude Code JSONL.
   - Format detector: Codex CLI session log.
   - Markdown fallback.
   - Output: one markdown document per session in `raw/conversations/<client>/<yyyy-mm-dd>-<session-id>.md` plus events in the `events` table.
   - Cursor and ChatGPT format detectors are post-MVP and added in a later phase.

2. **MCP-side capture** (from the user's recent addition to `12_conversation_capture.md`)
   - `mcp_session_log` table — migration `0007_add_mcp_session_log.sql`.
   - Every MCP tool call writes a row before returning.
   - The MCP server reads the `client_name`, `session_id`, `caller_model` from the MCP transport metadata.
   - `events` query supports `source='mcp_session'`.

3. **Hook installer** (from `18_secrets_and_hooks.md`)
   - `hooks/installer/claude_code.py`, `hooks/installer/codex.py`.
   - `_alexandria_managed: true` marker tagging.
   - Hook scripts: `hooks/scripts/claude-code-stop.sh`, `claude-code-precompact.sh`, `codex-stop.sh`, `codex-precompact.sh`.
   - Scripts call `alexandria capture conversation --detach`.

4. **`capture_queue` table** for concurrent-session serialization (from `18_secrets_and_hooks.md`).

5. **CLI commands**
   - `alexandria capture conversation [--detach]`
   - `alexandria captures list`
   - `alexandria captures purge --before <date>`
   - `alexandria hooks install <client>`
   - `alexandria hooks uninstall <client>`
   - `alexandria hooks verify [<client>]`
   - `alexandria hooks list`
   - `alexandria hooks status`

### Tests

- Unit: format detectors against fixture transcript files.
- Integration: install hook into a fake `~/.claude.json` file in a temp dir, simulate a session, verify capture lands.
- E2E: against a real Claude Code session if available in CI; otherwise against a real `~/.claude/projects/*.jsonl` file generated by a brief manual test session and committed as a fixture (with disclosure).
- E2E: spawn an MCP client subprocess, make tool calls, verify `mcp_session_log` rows land.

### Demoable end state
User runs `alexandria hooks install claude-code`, restarts Claude Code, has a session. After Stop fires, `alexandria captures list` shows the captured session. `alexandria why "anything from this session"` finds it.

### Phase exit criteria
- Hooks install/uninstall/verify works end-to-end.
- Concurrent sessions serialize through `capture_queue` without races.
- MCP-side capture records every tool call.
- **Three-agent review passes.**

---

## Phase 8 — Inference endpoint + scheduled synthesis (~2.5 weeks)

**Goal:** scheduled temporal synthesis runs unattended, producing weekly digests from event streams. Multi-provider LLM support.

### Deliverables

1. **LLMProvider abstraction full version** (from `11_inference_endpoint.md`)
   - Already partially in place from Phase 2. This phase extends it.
   - `llm/openai.py`: real OpenAI provider.
   - `llm/openai_compat.py`: OpenAI-compatible custom endpoints (Ollama, vLLM, SGLang, LiteLLM proxy).
   - `llm/budget.py`: full budget enforcement, per-operation routing in `[llm.routing]`.

2. **Scheduled temporal synthesis** (from `10_event_streams.md`)
   - `daemon/synthesis_worker.py`: a child of the daemon that runs the agent loop on schedule.
   - Reuses Phase 2's verifier and Phase 3's belief extraction.
   - Bounded budgets, dry-run preview.
   - Drafts land at `wiki/timeline/<period>.md` with `draft: true` frontmatter.

3. **CLI commands**
   - `alexandria llm list | add | test | cost`
   - `alexandria synthesize` (manual one-shot)
   - `alexandria synthesize enable | disable | pause | resume` (schedule control)
   - `alexandria synthesize rollback <run_id>`
   - `alexandria synthesize review`
   - `alexandria synthesize --dry-run` (preview cost before running)

4. **Caching strategy** (from `11_inference_endpoint.md`)
   - Stable `tools → system → messages` prefix construction.
   - `cache_control: ephemeral` markers on the last stable block per Anthropic docs (`research/raw/35_*`).
   - 1-hour TTL opt-in via per-preset config.
   - Honest per-path documentation: interactive path benefits, daemon path effectively does not.

### Tests

- Unit: provider abstraction roundtrips, budget enforcement edge cases.
- Integration: scheduled synthesis against a small workspace with seeded events, real Anthropic API call, real verifier pass, real commit.
- Integration: budget exhaustion mid-run → staged writes abandoned → live wiki untouched.
- Integration: rollback a committed synthesis run → git revert + state cleanup.

### Demoable end state
User has been running alexandria for a week with sources configured. They run `alexandria synthesize enable --workspace research`. The next Sunday at 03:00 the daemon spawns a synthesis run, produces `wiki/timeline/2026-w16.md`, the verifier checks it, it commits. Monday morning the user reads the digest. They can `alexandria synthesize review` to see drafts and `alexandria synthesize rollback <run_id>` if they don't like one.

### Phase exit criteria
- Scheduled synthesis runs unattended and reliably.
- Budget exhaustion is non-corrupting.
- Multi-provider works end-to-end against at least Anthropic + Ollama (local).
- **Three-agent review passes.**

---

## Phase 9 — Evaluation scaffold (~1.5 weeks)

**Goal:** M1, M2, M3, M4, M5 metrics implemented and gated. The freeze clause from Phase 4 onward is now formally enforced — synthesis is gated by M1/M2 health.

### Deliverables

1. **`eval_runs` and `eval_gold_queries` tables**
   - Migration `0008_add_eval.sql`.

2. **Metric implementations** (from `14_evaluation_scaffold.md`)
   - `eval/m1_citation_fidelity.py` — sample 50 random current beliefs, run deterministic hash check, semantic verifier vote.
   - `eval/m2_cascade_coverage.py` — for each ingest in the last 7 days, grep source key terms across wiki, compare to plan.json.
   - `eval/m3_retroactive_query.py` — frozen 30-query set, run query workflow, score against gold.
   - `eval/m4_cost.py` — roll up `llm-usage.jsonl`, compute cumulative + projected crossover.
   - `eval/m5_self_consistency.py` — sample claim pairs, vote on agreement.
   - All metrics share a `Metric` protocol with `async def compute(workspace) -> MetricResult`.

3. **Capability floor test fixtures** — 10 curated source documents shipped at `tests/fixtures/floor/`.

4. **Daemon-startup floor warning** — when the configured preset's floor score is degraded or untested, log a warning and surface in `alexandria status`.

5. **CLI commands**
   - `alexandria eval run [--metric M1|M2|...|all]`
   - `alexandria eval report [--since 30d]`
   - `alexandria eval gold add | list | import <file>`
   - `alexandria eval ack <metric> --reason "..."`
   - `alexandria eval floor --preset <name>`

6. **Synthesis gating** — the synthesis worker checks M1/M2 health before every run; broken metric blocks unless `--force` is passed.

### Tests

- Unit: each metric on synthetic fixtures with known expected scores.
- Integration: full eval run on a fixture workspace, verify scores fall in expected ranges.
- Integration: deliberately introduce a fabricated citation in a fixture wiki, run M1, verify it drops below threshold.
- E2E: capability floor test against Sonnet (real Anthropic call, small budget).

### Demoable end state
User runs `alexandria eval run --metric M1` and gets `M1: 0.97 (healthy)`. They run `alexandria eval report --since 30d` and see trend lines for all five metrics. They deliberately break a citation and re-run M1; they see it drop to 0.84 (broken) and synthesis is now blocked.

### Phase exit criteria
- All five metrics produce real scores against real fixtures.
- The freeze clause is enforced: broken M1 or M2 blocks scheduled synthesis.
- **Three-agent review passes.** This phase makes the entire architecture testable end-to-end, so the review is comprehensive.

---

## Phase 10 — More source adapters: Calendar, Gmail, Slack, Notion, Cloud (~2.5 weeks)

**Note:** This phase is GATED by Phase 9's M1+M2 producing healthy scores on the existing adapters. The freeze clause from `14_evaluation_scaffold.md` is now active.

**Goal:** the rest of the adapter catalog from `05_source_integrations.md` and `10_event_streams.md`.

### Deliverables

1. **OAuth flow framework**
   - `secrets/oauth.py`: local-callback OAuth client.
   - `alexandria auth register <provider>` — store client credentials.
   - `alexandria auth login <provider>` — interactive OAuth flow.
   - `alexandria auth list`, `auth revoke`.

2. **Google Calendar adapter** (`adapters/calendar.py`) — sync token incremental polling.

3. **Gmail adapter** (`adapters/gmail.py`) — historyId incremental sync.

4. **Slack adapter** (`adapters/slack.py`) — workspace-scoped, channel inclusion list, 90-day free-tier limit honored.

5. **Notion adapter** (`adapters/notion.py`) — block-to-markdown extraction, page-by-page polling.

6. **S3 / GCS / Drive bidirectional storage adapters** — read mode for source ingest, optional push mode for export-to-cloud.

### Tests

- Unit: OAuth callback handling, sync token state management.
- Integration: against test accounts on each provider (documented in test setup, with throwaway credentials in CI secrets).
- E2E: full multi-source workflow.

### Demoable end state
User configures Calendar + Gmail + Slack + Notion for their `customer-acme` workspace. The daemon polls everything in the background. The user opens Claude Code and asks *"how is the auth refactor going for Acme?"* — Claude Code traverses GitHub PRs + Slack discussions + meeting notes from calendar + email threads, builds a coherent answer.

### Phase exit criteria
- Real OAuth flows work for all providers.
- M1/M2 remain healthy after the new adapters' content is ingested.
- **Three-agent review passes.**

---

## Phase 11 — Operations polish (~1 week)

**Goal:** backup/restore, secret rotation, FTS5 verification, audit log, log redaction, crash dumps.

### Deliverables

1. **Backup and restore** (from `16_operations_and_reliability.md`)
   - `alexandria backup create [--output <path>]`
   - `alexandria backup restore <archive>`
   - Atomic SQLite snapshot via `sqlite3_backup_init`, git bundle for wiki history.

2. **FTS5 integrity** — `alexandria reindex --fts-verify`, `--fts-rebuild`, daemon-startup check.

3. **Schema migration robustness** — auto-backup before every migration, downgrade refuses, tampered checksum aborts.

4. **Crash dumps** — on unhandled exceptions, write `~/.alexandria/crashes/<timestamp>.txt` with traceback and state snapshot.

5. **Secret rotation, revocation, audit log** (full version from `18_secrets_and_hooks.md`)
   - `alexandria secrets rotate <ref>`
   - `alexandria secrets revoke <ref>`
   - `alexandria secrets reveal <ref> --confirm`
   - 7-day backup of rotated secrets.
   - `_audit.jsonl` for every sensitive operation.

6. **Log redaction** (`secrets/redactor.py`) — pass every log payload through the secret pattern matcher before write.

### Tests

- Backup/restore roundtrip against a populated workspace; verify nothing is lost.
- Migration tampered-checksum test.
- Secret rotation: rotate, verify old still in `.rotated/`, verify new active.
- Log redaction: write a log line containing a known secret value, verify it's redacted.

### Phase exit criteria
- All ops commands work.
- **Three-agent review passes.**

---

## Phase 12 — Documentation, packaging, release (~1 week)

**Goal:** v1.0.0 ready for `pip install alexandria`.

### Deliverables

1. **README.md, INSTALL.md, GETTING_STARTED.md** at the repo root.
2. **Final pass on all 20 architecture docs** — close any drift between architecture and implementation. The architecture docs are the spec; if implementation differed, the spec is updated to match (with justification in the doc).
3. **`pyproject.toml` polish** — version 1.0.0, classifiers, keywords, project URLs.
4. **Release notes** (`CHANGELOG.md`).
5. **CI/CD setup** — GitHub Actions running unit + integration on every PR, e2e nightly.
6. **Tag and publish** to PyPI under `alexandria`.

### Phase exit criteria
- A fresh user can `pip install alexandria` and follow GETTING_STARTED.md to a working setup.
- All architecture docs match the shipped code.
- **Three-agent review passes — final approval.**

---

## Cross-cutting risk register

Risks that span multiple phases. Each is tracked here so reviewers can flag them whenever they appear.

| Risk | Phase first relevant | Mitigation |
|---|---|---|
| The verifier is wrong (false positives or negatives) | Phase 2 | M1 metric in Phase 9 catches false positives. Manual override + audit log catches false negatives the user notices. |
| Cascade convergence policy doesn't fit a real-world contradiction | Phase 2 | The convergence policy in `15_cascade_and_convergence.md` is a single rule (hedge with dated marker); document edge cases as they appear; never silently overwrite. |
| LLM API costs spiral | Phase 2 | Hard budget caps in `[llm.budgets]`. M4 metric in Phase 9 publishes per-workspace cost. |
| Daemon crashes in production | Phase 6 | Supervised subprocess model + orphan sweep + crash dumps. |
| Schema migration fails midway | Phase 0 | Auto-backup before every migration. Downgrade is restore-from-backup, not in-place. |
| Hook breaks Claude Code session UX | Phase 7 | Hook is non-blocking via `--detach`. Failed hook does not block client. `hooks verify` catches stale hooks. |
| Secret leaks into a log file | Phase 4, 11 | `SecretRedactor` runs on every log emission. The verifier rejects wiki writes containing known secrets. |
| FTS5 desync (silent search corruption) | Phase 0, 11 | `fts_verify` runs on every daemon start. `fts_rebuild` is idempotent. |
| The freeze clause is bypassed | Phase 4 | Implementation enforcement: `source add` checks M1/M2 health before allowing new adapters past the documented MVP set. |
| Concurrent MCP clients race on writes | Phase 1, 2 | Per-workspace `fcntl` advisory lock on commit. Stale plans are rejected by the verifier. |

## Review protocol

After each phase reaches its exit criteria, the same three specialist agents review the actual deliverables:

- **`llm-architect`** reviews the LLM-application aspects: tool surface, prompt structure, caching strategy, agent loop correctness, capability assumptions.
- **`ai-engineer`** reviews the AI system quality: workflow correctness, evaluation outcomes, citation fidelity, failure mode handling, end-to-end behavior.
- **`mlops-engineer`** reviews the operational aspects: schema migrations, daemon stability, observability, recovery, secret handling, rate limiting.

Reviews look at:
1. **The actual code** that landed, not the intended code.
2. **The actual tests** that pass, not the planned tests.
3. **The actual demo** running end-to-end, not a description of it.

Reviews produce structured findings:
- **Blockers**: the phase cannot ship until these are fixed.
- **Important**: should be fixed in a follow-up before the next phase starts.
- **Nice to have**: tracked in the risk register or the open-questions doc.

A phase exits when:
1. All exit criteria are met.
2. All blocker findings from the three reviews are resolved.
3. A short Phase Completion Report is written summarizing what shipped, what was reviewed, what changed, and what's deferred to the next phase.

## What the reviewers should look at right now

This document is the **first checkpoint**: the plan itself, not any phase's output. The reviewers are asked to evaluate whether the plan is sound before any code is written. Specific questions:

1. **Is the phase ordering correct?** Does each phase build on real foundations from prior phases, or are there hidden dependencies that would force back-tracking?
2. **Are the phase boundaries right?** Is anything too big, too small, or scoped to leave the system in a non-functional state at phase boundaries?
3. **Are the time estimates realistic?** Each phase has a duration estimate; reviewers should challenge those.
4. **Are the test strategies adequate** for each phase, given the no-fakes constraint?
5. **What's the single biggest risk** in this plan, and is the plan honest about it?
6. **What's missing** — is there a deliverable in any architecture doc that has no home in this plan?
7. **Are the freeze clauses and gating mechanisms** (Phase 9 gating Phase 10, etc.) correctly placed?

## Summary

13 phases, ~22-26 weeks of single-developer work, every phase producing a demoable end-to-end system, every phase ending with a three-agent review, no fakes, no mocks, no stubs, no placeholders (with the one documented exception of `not yet shipped` messages on the discoverable CLI), tests against real dependencies, DRY/SOLID/KISS applied throughout.

The plan is binding once the first three-agent review approves it. After that, every phase exits by passing the same three reviews. Implementation begins at Phase 0 once this plan is approved.
