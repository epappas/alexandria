# Async ingest jobs

Large ingests (whole GitHub repos, big local directories, batches of
URLs) used to block the tool-use call for hours — and because the
interactive session sat on that, it also quietly burned through Opus
quota while waiting. As of v0.37, ingest is an **async job**: it
enqueues, returns quickly, and a worker inside the MCP server processes
it with Haiku, independent of whatever model powers your conversation.

## TL;DR

```bash
# Enqueue an ingest from an agent / MCP client — returns either the
# result (small job) or a job handle (big job).
ingest(source="https://github.com/vllm-project/vllm", scope="docs")

# From the terminal:
alxia jobs list
alxia jobs status job-20260422-abcd1234efgh
alxia jobs tail   job-20260422-abcd1234efgh   # stream progress
alxia jobs cancel job-20260422-abcd1234efgh   # cooperative cancel
```

## Why this shape

Three problems with the old synchronous ingest:

1. **No visibility.** `ingest()` held the tool call for hours. The
   agent had no stdout to read, no partial output to share. You had to
   trust silence for 10h. That's the bug that triggered this.
2. **Opus burn.** An Opus session orchestrating long ingests stayed
   active the whole time, consuming Opus tokens while it waited on
   work that itself was running Haiku.
3. **No cancellation.** Only way out was killing the MCP server,
   which orphaned state.

The async model fixes all three.

## Architecture

```
agent / CLI → ingest() → enqueue_ingest() → jobs table (SQLite)
                                                 ↑ claim
                            worker loop (asyncio task inside MCP server)
                                                 ↓
                                            runs ingest_file / ingest_repo
                                         updates progress + run_ids
                                         honours cancel between files
```

The worker is an asyncio task started alongside the MCP server (stdio
or HTTP). One worker per server process, single concurrency — this is
the smallest useful unit and keeps rate-limit math simple.

Jobs persist in SQLite. If the server dies mid-ingest, the next server
picks up queued work. Running jobs are left in `running` state until
the next worker claims them (future work: reclaim stuck jobs).

## The `ingest` tool's new contract

```
ingest(source,
       workspace=None,
       topic=None,
       no_merge=False,
       scope="all",     # or "docs"
       wait_s=60)       # 0 = always async
```

Behavior:

- Enqueues a job immediately, regardless of `wait_s`.
- Polls the job for up to `wait_s` seconds. If it finishes in time,
  returns the full result inline (so short URL ingests still feel
  synchronous).
- If it doesn't finish in time, returns a compact job handle with the
  `job_id` and progress-so-far. Agent is expected to call `jobs_status`
  later.

## Scope control

Repositories and directories default to `scope="all"` — every supported
file goes through the pipeline. For large codebases, use `scope="docs"`
to restrict to:

- `README*` at the root
- top-level `*.md`, `*.rst`, `*.txt`
- everything under `docs/`, `doc/`, `documentation/`

Typical repo sizes with the two scopes:

| Repo | `scope="all"` | `scope="docs"` |
|------|--------------:|----------------:|
| `vllm-project/vllm` | 4,698 files / ~40h | 23 files / ~20min |
| `llm-d/llm-d` | 467 files / ~6h | 12 files / ~10min |

Rule of thumb: default to docs for repos unless the user explicitly
wants the codebase.

## Model pinning

`~/.alexandria/config.toml`:

```toml
[jobs]
model = "haiku"          # pinned on the ingest subprocess env
poll_interval_s = 1.0
default_wait_s = 60
```

The worker sets `ALEXANDRIA_CLAUDE_MODEL=<jobs.model>` on its process
environment before running the LLM work for each job. That env is
picked up by the Claude Code SDK provider in `llm_ingest.py` and
passed as `--model` to `claude -p`. This happens regardless of what the
MCP server was registered with — so accidental Opus ingestion is
impossible when `jobs.model = "haiku"`.

## Cancellation

Cancellation is cooperative. `jobs_cancel` (MCP) or
`alxia jobs cancel <id>` (CLI) marks the job as cancelled in the
database. The worker checks this flag between files and exits the
ingest loop cleanly. Already-committed wiki pages stay.

If the worker is stuck on a single long file (big PDF, slow LLM call),
cancellation takes effect as soon as that file completes — not mid-file.

## CLI reference

```bash
alxia jobs list                   # recent jobs in the current workspace
alxia jobs list -s running        # only running
alxia jobs list -w other          # specific workspace
alxia jobs list -n 100            # more rows

alxia jobs status <job_id>        # full detail including progress + ETA
alxia jobs tail   <job_id>        # stream updates until terminal
alxia jobs cancel <job_id>        # cooperative cancel
```

## Observed behaviour you might wonder about

- **Jobs that never leave `queued`.** The worker runs inside the MCP
  server. If no one has started `alxia mcp serve` (or your agent has
  not connected to one), nothing processes the queue. Start a server
  and the queue drains.
- **`started_at` set but no progress.** Worker picked up the job and
  is in the initial scope-counting phase (cloning a repo, walking a
  directory). Progress updates begin once the first file is processed.
- **ETA shows `~XXh`.** Derived from files-done / elapsed-seconds; it
  gets more accurate as more files complete. Early ETAs are noisy.

## What's not yet built

- Parallel workers (per-workspace or shared). Today it's one at a time.
- Reclaim-stuck-running logic on server restart. A crashed worker
  leaves the job as `running`; you can reset it with
  `alxia jobs cancel <id>` and re-ingest.
- Priority queue. Jobs run strictly FIFO.
