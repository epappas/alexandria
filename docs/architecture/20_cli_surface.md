# 20 — CLI Surface

> **Status:** Implementation contract.
>
> The `llmwiki -h` output reproduced below is the canonical user-facing CLI for v1. Every command is grounded in a specific architecture doc (mapping table further down). When implementation begins, this doc is binding — every command listed must exist and behave as described, and any command not listed must be justified by a corresponding architecture doc update before being added.

## Why this doc exists

llmwiki has three audiences with three surfaces:

| Surface | Audience | Defined in |
|---|---|---|
| **CLI** | The user, at the terminal | This doc (`20_cli_surface.md`) |
| **MCP tool surface** | Connected agents (Claude Code, Cursor, Codex, ...) | `04_guardian_agent.md` + `08_mcp_integration.md` |
| **Engine internals** | Daemon, scheduler, verifier, runs state machine | `06_data_model.md`, `13_hostile_verifier.md`, `16_operations_and_reliability.md` |

Each surface has its own audience, its own conventions, its own stability guarantees. They overlap in subject matter (both `llmwiki ingest` and the MCP `write` tool eventually trigger the same staged-run mechanism) but never in interface. **This doc pins down the user surface.**

A user who reads `llmwiki -h` and starts typing should be able to do every operation we have designed without ever opening an architecture doc. The CLI is the implementation of "knowledge engine, not chat client" at the human-facing level — every command is something the user runs to *configure*, *inspect*, or *trigger* the engine. Conversational interaction with the engine happens via Claude Code through MCP, not at the shell.

## The canonical `llmwiki -h` output

This is the binding specification. Implementation must produce help text equivalent to this, every command must exist, every flag must work, every grouping must be preserved.

```
$ llmwiki -h

llmwiki — local-first single-user knowledge engine
A Python tool that accumulates your gathered knowledge (raw sources, compiled wiki
pages, event streams, AI conversations) and exposes it via MCP to connected agents
like Claude Code for retroactive query and synthesis.

llmwiki is NOT a chat client. Interactive conversations happen in your existing
MCP-capable agent (Claude Code, Cursor, Codex, Claude Desktop, Windsurf, ...).
llmwiki is the knowledge engine those agents connect to.

USAGE
  llmwiki <command> [<subcommand>] [flags]
  llmwiki <command> -h                Show help for a command group

QUICK START
  llmwiki init                        Initialize ~/.llmwiki/ and the global workspace
  llmwiki mcp install claude-code     Register llmwiki with your MCP client
  llmwiki status                      Show what's happening right now
  llmwiki why "<topic>"               What do I believe about X and why

KNOWLEDGE OPERATIONS              the three verbs plus belief revision
  ingest <source>                     Compile a source into the wiki (staged + verified)
  ingest pending                      Process all pending sync + subscription items
  query "<question>"                  Answer from the wiki; --save archives the answer
  lint [--auto-fix]                   Auto-fix deterministic; verifier reports heuristic
  why "<topic | belief_id>"           Belief explainability + provenance + history (read-only)
  synthesize [--dry-run]              Manually trigger a temporal synthesis run (writes)
  synthesize enable | pause | resume  Schedule control for unattended synthesis
  synthesize rollback <run_id>        Revert a committed synthesis run
  synthesize review                   List drafts awaiting your review

WORKSPACES AND PROJECTS
  workspace use <slug>                Set the current workspace
  workspace current                   Print the current workspace
  workspace list                      List all workspaces with counts
  project create <name>               Create a new project workspace
  project info <name>                 Show workspace state, sources, eval health
  project rename <old> <new>          Rename a workspace
  project delete <name>               Soft-delete a workspace (moves to .trash/)

SOURCES, SUBSCRIPTIONS, EVENTS    pulling content into raw/
  source add <type>                   local | obsidian | notion | github | gitlab |
                                      gist | arxiv | s3 | gcs | drive | dropbox |
                                      gmail | calendar | slack | discord | rss |
                                      substack | youtube | mastodon | reddit | ...
  source list                         All adapters + last run + circuit-breaker state
  source remove <id>                  Remove a source adapter
  sync [<source-id>]                  Run sync for one or all sources now
  subscriptions list                  Pending subscription items grouped by source
  subscriptions show <id>             Render one item
  subscriptions ingest [filter]       Trigger ingest for matching pending items
  subscriptions dismiss <id>          Mark as read without ingesting
  subscriptions poll                  Force-poll all subscriptions

CONVERSATION CAPTURE              Claude Code / Cursor / Codex / ChatGPT / etc.
  capture conversation [--detach]     Mine transcripts now (called by hooks; --detach for async)
  captures list                       Captured sessions per client + counts
  captures purge --before <date>      Purge captures older than a date
  hooks install <client>              Install Stop + PreCompact auto-save hooks
  hooks uninstall <client>            Remove llmwiki-managed hook blocks (marker-tagged)
  hooks verify [<client>]             Check installed hooks point to a valid binary
  hooks list                          All installed hooks across clients
  hooks status                        Hook invocation counts + capture_queue depth

MCP INTEGRATION                   llmwiki is the knowledge engine; agents connect to it
  mcp serve                           Start stdio MCP server in OPEN mode (all workspaces)
  mcp serve --workspace <slug>        Start in PINNED mode (locked to one workspace)
  mcp install <client>                Register with claude-code | cursor | codex |
                                      claude-desktop | windsurf | zed | continue
  mcp status                          Running MCP sessions and bound workspaces

BELIEFS AND PROVENANCE            why do I believe X
  why "<query>" [--since <date>]      Belief lookup: current + history + verbatim quotes
  beliefs list --topic <t>            All current beliefs in a topic
  beliefs history <belief_id>         Full supersession chain back to first assertion
  beliefs supersede <old> <new>       Manual supersession (rare; for corrections)
  beliefs verify [--workspace <s>]    Re-validate every quote anchor against live raw
  beliefs export [--format json|csv]  Export the belief set

EVALUATION                        M1-M5 metrics; gates scheduled synthesis
  eval run [--metric M1|M2|M3|M4|M5]  Run one or all metrics now
  eval report [--since 30d]           Show metric trends and current health
  eval gold add | list                Manage M3 frozen retroactive query benchmark
  eval gold import <file>             Bulk import gold queries from YAML
  eval ack <metric> --reason "..."    Acknowledge a broken metric to unblock automation
  eval floor --preset <name>          Test a model preset against the capability floor

INFERENCE ENDPOINT                daemon-owned only; interactive uses your MCP client
  llm list                            List configured presets
  llm add <name>                      Add a provider preset (anthropic | openai |
                                      gemini | openai-compatible)
  llm test <preset>                   Verify credentials + endpoint with a ping
  llm cost [--since 30d]              Cumulative LLM cost from telemetry

OPERATIONS AND RELIABILITY        daemon, supervision, recovery
  daemon start | stop | status        Start, stop, or inspect the local daemon
  status [--json] [--watch]           Operational dashboard
  doctor                              Health checks with actionable remediation
  runs show <run_id>                  Inspect a staged run: verdict, diff, beliefs
  logs show <run_id>                  Merged log view across all 7 log families
  reindex [--fts-verify]              Rebuild SQLite from filesystem
  reindex --rebuild-beliefs           Rebuild wiki_beliefs from .beliefs.json sidecars
  reindex --fts-rebuild               Force FTS5 rebuild
  db migrate                          Apply pending schema migrations (auto-backup first)
  db status                           Current schema version + pending migrations
  backup create [--output <path>]     Atomic snapshot of raw + wiki + db + secrets + config
  backup restore <archive>            Restore from a backup tarball
  verify override <run_id>            Manually override a hostile-verifier reject

SECRETS AND CREDENTIALS           encrypted at rest, OS keyring + headless fallback
  secrets set <ref>                   Store a new secret (read from stdin or file)
  secrets rotate <ref>                Rotate a secret; old value kept 7 days for unroll
  secrets revoke <ref>                Wipe a secret + optionally disable adapters
  secrets list                        Names + types + last-used (never values)
  secrets reveal <ref> --confirm      Print value (audit-logged)
  secrets verify <ref>                Decrypt + non-destructive ping
  auth register <provider>            Store OAuth client credentials for a provider
  auth login <provider>               OAuth flow with local callback
  auth list                           Show authenticated providers + token expiry
  auth revoke <provider>              Revoke OAuth tokens for a provider

EXPORT AND PORTABILITY
  export --workspace <slug>           Export a workspace as obsidian-zip | raw-md | html | json
  paste --workspace <slug> --title T  One-shot capture from stdin into raw/local/

GLOBAL FLAGS
  -h, --help                          Show this help (or sub-help with <command> -h)
  -V, --version                       Print version
  -w, --workspace <slug>              Override workspace for this command
  -v, --verbose                       Verbose log output
  -q, --quiet                         Suppress non-essential output
  --json                              Emit JSON instead of human output (where supported)
  --no-color                          Disable terminal colors
  --dry-run                           Preview without committing

ENVIRONMENT
  LLMWIKI_HOME                        Override ~/.llmwiki/ data directory
  LLMWIKI_WORKSPACE                   Override default workspace
  LLMWIKI_VAULT_PASSPHRASE            Headless secrets vault passphrase
  LLMWIKI_NO_VERIFY                   Bypass hostile verifier (with audit; per-run too)
  LLMWIKI_VERBOSE                     Hook verbose mode

EXAMPLES
  # First-time setup
  llmwiki init
  llmwiki project create customer-acme
  llmwiki mcp install claude-code

  # Configure data sources
  llmwiki source add github --workspace customer-acme
  llmwiki source add slack  --workspace customer-acme
  llmwiki source add gmail  --workspace customer-acme
  llmwiki sync

  # Day-to-day use (mostly happens INSIDE Claude Code via MCP)
  llmwiki status                                 # what's running, what's pending
  llmwiki why "auth refactor"                    # belief + provenance + history
  llmwiki ingest ~/papers/rfc-0034.pdf          # compile a source
  llmwiki subscriptions list                     # what's pending in the inbox

  # Health and operations
  llmwiki doctor                                 # health check
  llmwiki eval run --metric M1                   # check citation fidelity
  llmwiki runs show 2026-04-16-abc123           # inspect a staged run
  llmwiki backup create --output ~/backups/

CURRENT STATE
  Default workspace:  global
  Data directory:     ~/.llmwiki
  Daemon:             not running    (start with: llmwiki daemon start)
  MCP server:         registered with claude-code (open mode)
  Schema version:     7
  Eval health:        M1 0.97  M2 0.93  M3 0.84  M5 0.96  (all healthy)
  Last backup:        35h ago         (run: llmwiki backup create)

DOCUMENTATION
  Architecture:       docs/architecture/         (20 docs, ~6,250 lines)
  Research:           docs/research/reference/   (14 reference docs over 37 raw sources)
  Reviews:            docs/research/reviews/     (3 reviewer reports)

  https://github.com/epappas/llmwiki            (when published)

llmwiki accumulates your gathered knowledge so you can retroactively
query, retrieve, and review months of work. Knowledge engine, not chat.
```

## Command-to-doc mapping

Every CLI command traces back to a specific architecture doc. This table is the binding map — if a command above does not appear in the right column, it is a bug to be fixed (either remove the command from the CLI or add it to the architecture doc).

| Command group | Architecture doc(s) |
|---|---|
| `init`, `paste`, `export`, global flags | `02_system_architecture.md` |
| `workspace`, `project` | `03_workspaces_and_scopes.md` |
| `ingest`, `query`, `lint` (the three verbs) | `04_guardian_agent.md` |
| `source`, `sync` (the adapter surface) | `05_source_integrations.md` |
| `subscriptions` | `09_subscriptions_and_feeds.md` |
| `mcp serve`, `mcp install`, `mcp status` | `08_mcp_integration.md` |
| `synthesize` (manual + scheduled), `runs show` | `10_event_streams.md` (synthesis intent) + `13_hostile_verifier.md` (runs / `verify override`) |
| `llm list/add/test/cost` | `11_inference_endpoint.md` |
| `capture`, `captures`, `hooks` | `12_conversation_capture.md` (capture loop) + `18_secrets_and_hooks.md` (hooks lifecycle) |
| `eval` (run, report, gold, ack, floor) | `14_evaluation_scaffold.md` |
| `daemon`, `db`, `backup`, `reindex`, `synthesize pause/resume/rollback/review` | `16_operations_and_reliability.md` |
| `status`, `doctor`, `logs show` | `17_observability.md` |
| `secrets`, `auth` | `18_secrets_and_hooks.md` |
| `why`, `beliefs` | `19_belief_revision.md` |

## Design conventions (binding for implementation)

These are the conventions the CLI follows. They are part of the contract.

### 1. Single binary, single entry point

There is **one** `llmwiki` executable. Subcommands dispatch to the daemon, the MCP server, the CLI, or the tooling — all from the same Python entry point in `pyproject.toml`. This matches `02_system_architecture.md`'s "three entry points, one data directory" framing: the CLI, `llmwiki mcp serve`, and `llmwiki daemon start` are all the same binary invoked with different arguments.

There are **no** separate `llmwiki-daemon`, `llmwiki-mcp`, or `llmwiki-cli` binaries. KISS: one thing to install, one thing to upgrade, one thing to alias.

### 2. Two-tier help (gh / kubectl pattern)

`llmwiki -h` shows command groups with one-line descriptions and hints at sub-commands. `llmwiki <group> -h` drills into the full sub-command set with full flag help.

This is the same pattern as `gh`, `kubectl`, `docker`. It scales: a user adopting llmwiki sees the surface in 60 seconds; a user already familiar drills directly to what they need.

### 3. Command groups are nouns; sub-commands are verbs

`llmwiki source add` not `llmwiki add-source`. `llmwiki secrets rotate` not `llmwiki rotate-secret`. The noun-verb order is consistent across every group, which lets the user predict commands they have not yet learned.

The exceptions are the **headline verbs** (`ingest`, `query`, `lint`, `why`, `synthesize`, `sync`, `init`, `paste`, `export`) which are top-level because they are the daily-use commands and burying them under a group would slow muscle memory.

### 4. `-h` and `--help` are universal

Every command, every sub-command, accepts `-h`. Implementations that do not honor this on a sub-command are non-conformant.

### 5. Global flags are universal too

`-w/--workspace`, `-v/--verbose`, `-q/--quiet`, `--json`, `--no-color`, `--dry-run` work on every command where they are meaningful. A user who learned `--json` once expects it to work on `status`, `eval report`, `runs show`, `secrets list`, etc.

### 6. `--json` is the agent / scripting interface

Every command that produces structured output supports `--json`. This is how scripts, monitoring tools, and the agent itself (when calling out via shell from inside Claude Code) consume llmwiki state.

### 7. Read-only commands never require confirmation

`llmwiki status`, `llmwiki why ...`, `llmwiki beliefs list`, `llmwiki secrets list`, `llmwiki runs show ...`, `llmwiki logs show ...` — none of these prompt. They print and exit.

### 8. Destructive commands require either `--confirm` or stdin redirection

`llmwiki secrets reveal <ref>` — requires `--confirm` flag. Audit-logged.
`llmwiki secrets revoke <ref>` — requires `--confirm` flag. Audit-logged.
`llmwiki project delete <name>` — interactive prompt unless `--yes` is passed.
`llmwiki backup restore <archive>` — refuses to run over a non-empty target unless `--into <other>`.
`llmwiki verify override <run_id>` — requires `--reason "..."` and is audit-logged.

### 9. Idempotency where possible

`llmwiki init` on an existing install is a no-op. `llmwiki hooks install <client>` re-running updates the marker-tagged block in place. `llmwiki source add` with the same config is a no-op. `llmwiki sync` is always idempotent (content-hash dedup from `05_source_integrations.md`).

### 10. The CLI never opens a chat REPL

There is no `llmwiki chat`, no `llmwiki ask`, no `llmwiki shell`. Interactive conversation happens in the user's MCP client (Claude Code, Cursor, etc.). This is the load-bearing design choice from invariant #14 — *llmwiki is a knowledge engine, not a chat client* — and the CLI must respect it. Adding a chat-shaped command would be a regression against invariant #14 and requires updating `01_vision_and_principles.md` first.

## Important command pairings (the distinctions that matter)

These are pairs the user may confuse if the help text is read carelessly. The implementation should sharpen the one-liners and the `-h` sub-help to make the contrast explicit.

### `why` vs `synthesize` — read versus write

**This is the most important distinction in the CLI.** Both touch knowledge but in opposite ways.

| | `why "<topic>"` | `synthesize` |
|---|---|---|
| **What it is** | Read a belief and its provenance | Run the agent to write new wiki content |
| **Reads or writes?** | **Read-only.** Never modifies the wiki. | **Write.** Stages new pages, goes through the verifier. |
| **LLM call?** | **No** in the basic case — pure SQL over `wiki_beliefs` + `wiki_claim_provenance`. Optional `--re-verify` adds a verifier semantic check. | **Yes.** Full guardian agent loop with hostile verifier. The most expensive command in llmwiki. |
| **Cost** | Free / sub-second | Bounded by `[llm.budgets.scheduled_synthesis]` — typically $1-3 per run, 30-60s wall time |
| **Scope** | One belief and its supersession history | A time window of events → multiple new wiki pages |
| **Trigger** | User asks any time | Scheduled (weekly cron) or manual (`llmwiki synthesize`) |
| **Defined in** | `19_belief_revision.md` | `10_event_streams.md` + `11_inference_endpoint.md` |
| **Use case** | *"What did we decide about auth, and why?"* | *"Compile this week's project activity into a digest."* |

**`why` reads what the engine already believes; `synthesize` produces new content for the engine to believe.** They are complementary, not overlapping.

In the three-operation vocabulary from `04_guardian_agent.md`:
- `why` is a flavor of **query** — pure retrieval, no writes, no agent loop in the basic case.
- `synthesize` is a flavor of **ingest** — runs the cascade workflow over event streams instead of a single user-provided source.

### `query` vs `why` — open question versus belief lookup

| | `query "<question>"` | `why "<topic>"` |
|---|---|---|
| **Input shape** | Open-ended natural-language question | Topic name, subject, or `belief_id` |
| **Output** | Synthesized answer with citations | Structured belief rows with provenance chain |
| **LLM call?** | **Yes** — runs the agent loop over the wiki | **No** in the basic case — SQL lookup |
| **Use case** | *"What's the state of the art on auth?"* | *"What do I believe about Acme's OAuth endpoint, and why?"* |

Rule of thumb: if you would write a sentence to ask the question, use `query`. If you have a noun in mind (a topic, a thing, a fact), use `why`. The user can always escalate from `why` to `query` if they want a synthesized narrative — but starting with `why` is cheaper, faster, and more explainable.

### `ingest` vs `synthesize` — user-source versus event-stream

| | `ingest <source>` | `synthesize` |
|---|---|---|
| **Triggered by** | User points at a specific source | User triggers manually OR daemon cron |
| **Input** | One or more raw documents the user names | Event streams + pending raw sources accumulated since last run |
| **Output** | New/updated wiki pages tied to that source | A `wiki/timeline/<period>.md` digest + entity-page Recent Activity updates |
| **Use case** | *"Compile this paper into the wiki."* | *"Compile this week's project activity into a digest."* |

Both go through the same staged-run + hostile verifier mechanism. Both produce wiki writes. They differ in **what they read** and **what they produce**: `ingest` is source-driven, `synthesize` is time-driven.

### `sync` vs `subscriptions poll` — adapter sync versus subscription poll

| | `sync` | `subscriptions poll` |
|---|---|---|
| **Targets** | All `SOURCE` and `EVENT_STREAM` adapters | Only `SUBSCRIPTION` adapters |
| **Use case** | *"Refresh everything from external sources."* | *"Force-poll my newsletter feeds and Twitter feeds now."* |

`sync` is the broad refresh. `subscriptions poll` is the narrow one. Both produce items in `raw/`; neither runs the agent.

### `runs show` vs `logs show` — staged run versus log-file merge

| | `runs show <run_id>` | `logs show <run_id>` |
|---|---|---|
| **Source** | The `runs` table from `13_hostile_verifier.md` | The merged JSONL log files from `17_observability.md` |
| **What you see** | Run metadata, verdict, diff, beliefs, staging directory | Every log line across all 7 families, timestamp-sorted |
| **Use case** | *"Why did this run reject?"* | *"What did this run actually do, step by step?"* |

Both take a `run_id`. `runs show` is the structured view; `logs show` is the timeline view. They are complementary.

## Things the CLI design surfaced that need follow-up in other docs

Designing the CLI surface exposed a few places where the architecture docs are slightly looser than they should be. These are not bugs — they are gaps the CLI cannot answer alone and that need to be tightened before implementation:

1. **`workspace list` vs `project list` naming.** `03_workspaces_and_scopes.md` uses `project list` exclusively, but the CLI surface above also offers `workspace list` because the global workspace is also a workspace. We should pick one and stick with it. **Recommendation: keep both as aliases**, with `workspace list` as the canonical form (since it includes the global workspace) and `project list` as the alias for users who want only project workspaces (filters out `global`).

2. **`captures list` is not in `12_conversation_capture.md`.** The doc explicitly mentions `captures purge` but not `captures list`. The CLI needs a way to inspect captured sessions. **Recommendation: add `captures list` to doc 12 alongside `captures purge`.**

3. **`eval gold import <file>` format is not specified.** `14_evaluation_scaffold.md` mentions YAML import but does not pin the schema. **Recommendation: add a YAML schema example to doc 14.**

4. **Global `--dry-run` flag** is in this doc but not consistently mentioned in every command's individual doc. `synthesize --dry-run` is in `11_inference_endpoint.md`; `ingest --dry-run`, `lint --dry-run`, `eval run --dry-run`, `backup create --dry-run` should all work the same way. **Recommendation: add a "Global flags" reference section to `02_system_architecture.md` that lists `--dry-run` and other globals once, then reference it from individual docs.**

5. **`ENVIRONMENT` variables are scattered across docs.** `LLMWIKI_HOME` (doc 02), `LLMWIKI_WORKSPACE` (doc 03), `LLMWIKI_VAULT_PASSPHRASE` (doc 18), `LLMWIKI_NO_VERIFY` (doc 13), `LLMWIKI_VERBOSE` (doc 12). **Recommendation: consolidate into a single environment-variable reference in `02_system_architecture.md`.**

6. **`status` output schema is not formally defined.** `17_observability.md` shows an example JSON blob but does not commit to it as a schema. **Recommendation: pin the schema in doc 17 with a versioned `STATUS_SCHEMA_VERSION` so scripting tools can rely on it.**

7. **`source add <type>` — the canonical adapter type list.** The help text lists ~20 types; some are MVP and some are post-MVP per docs 05/09/10. **Recommendation: add a concrete "supported at MVP vs post-MVP" table to `05_source_integrations.md` so the CLI implementation knows which types must work on day one.**

These follow-ups are tracked here, not in `07_open_questions.md`, because they are CLI-implementation prerequisites. As implementation begins, they should be resolved first.

## SOLID / DRY / KISS application to the CLI design

### DRY

- **One binary** dispatching to all roles (CLI, daemon, MCP server). Not three binaries with overlapping config.
- **One global flag set** (`-h`, `-V`, `-w`, `-v`, `-q`, `--json`, `--no-color`, `--dry-run`) reused across every command. The user learns the flags once.
- **One verb pattern** (noun group + verb sub-command) with the headline verbs as the only top-level exceptions. Predictable.
- **One help format** across the whole binary — same column widths, same example block style, same one-liner length, same documentation footer.
- **One audit log path** (`~/.llmwiki/secrets/_audit.jsonl`) used for every sensitive operation across every command.
- **One `run_id` correlation** spanning every log family for any command that produces a run.

### SOLID

- **Single Responsibility:** every command does one thing. `synthesize` produces digests; `eval` measures; `runs show` inspects; `verify override` overrides. No omnibus commands.
- **Open/Closed:** adding a new source adapter is `source add <new-type>` — no changes to the CLI surface. Adding a new metric is a new `eval` flag value. Adding a new client to hooks is `hooks install <new-client>`. The CLI is stable; capabilities extend it.
- **Liskov:** every command group honors the same interface contract: `<group> -h` works, `<group> <subcommand> -h` works, global flags work, exit codes are conventional (0 = success, 1 = user error, 2 = system error, 3 = circuit breaker / quota / budget tripped).
- **Interface Segregation:** the CLI exposes only what the user needs. Engine internals (the `runs` table state machine, the verifier's per-claim findings, the `wiki_claim_provenance` join behavior) are not user-facing surfaces — they are accessed via `runs show` and `why`, which return high-level structured data, not raw rows.
- **Dependency Inversion:** the CLI depends on protocol interfaces (`Verifier`, `LLMProvider`, `SourceAdapter`, `SecretVault`), not concrete implementations. Tests can substitute fakes; production injects real implementations.

### KISS

- **Two help tiers, not five.** `llmwiki -h` shows groups; `llmwiki <group> -h` shows commands; `llmwiki <group> <command> -h` shows flags. Three levels max. Going deeper is friction.
- **Boring conventions.** `--json` for machine output. `--dry-run` for previews. `-w` for workspace. `--confirm` for destructive ops. Nothing the user has not seen in `gh`, `kubectl`, or `docker`.
- **No DSLs.** No query language at the CLI level. No template syntax in flags. No scripting language for cron expressions (we use ISO 8601 cadences in config, not cron strings).
- **No interactive wizards by default.** `init` can prompt for setup, `secrets set` reads from stdin, `auth login` opens a browser. Otherwise the CLI is non-interactive — scripts can rely on it.
- **One binary in `$PATH`.** The user installs llmwiki via `pip install llmwiki` or `pipx install llmwiki` and gets exactly one new command in their shell. Dependencies are bundled or vendored.

## What this doc does NOT cover

The CLI surface is a contract on **what commands exist and how they group**. It is not a contract on:

- **The framework used to build the CLI.** Typer, Click, argparse — implementation choice. The contract is the help output, not the parser library.
- **Exit codes beyond the conventional four.** Implementation adds finer-grained codes as needed; the documented ones (0 / 1 / 2 / 3) are the floor, not the ceiling.
- **Output formatting details.** Color, table widths, padding, truncation. As long as `--json` produces stable structured output and the human format is readable, the implementation chooses.
- **The daemon's internal protocol** — Unix socket, pipe, in-process. That is `16_operations_and_reliability.md`'s domain.
- **The MCP tool surface** the agent sees. That is `04_guardian_agent.md` + `08_mcp_integration.md`.
- **Stability across versions.** v1 freezes the surface above. v2 may add commands; it must not remove or rename them without a deprecation cycle.

## Implementation contract

When implementation begins:

1. **Every command in the help output above must exist** and produce help text equivalent to its line.
2. **Every documented sub-command must work** as described, even if the underlying feature is a stub returning `not implemented yet` for now. The user must be able to discover the surface.
3. **Every global flag must be honored** by every command where it makes sense. Implementations that drop flags silently are non-conformant.
4. **Every exit code mentioned** (0 success, 1 user error, 2 system error, 3 quota/budget/circuit-breaker) must be returned in the documented cases.
5. **Every command-to-doc mapping** must hold. If a command is added without a corresponding architecture doc section, the architecture doc is updated first.
6. **The "Things that need follow-up" list above is binding** — those gaps must be closed in the referenced architecture docs before the CLI surface is implemented end-to-end.

This is how the CLI stays coherent with the architecture across implementation. The CLI is the user's entry point; the architecture is the spec; this doc is the bridge.

## Summary

`llmwiki -h` is a binding contract for the v1 user surface. Every command traces to an architecture doc. Two-tier help (`llmwiki -h` for groups, `llmwiki <group> -h` for sub-commands) follows the `gh`/`kubectl` convention. Global flags (`-h`, `-V`, `-w`, `-v`, `-q`, `--json`, `--no-color`, `--dry-run`) are universal. Headline verbs (`ingest`, `query`, `lint`, `why`, `synthesize`, `sync`, `init`, `paste`, `export`) live at the top; everything else is grouped by noun. There is no chat command — interactive happens in the connected MCP client, which is the load-bearing design choice from invariant #14.

The seven follow-up gaps in the existing docs are tracked in this doc and must be closed before implementation. The design conventions (single binary, two-tier help, noun-verb sub-commands, universal global flags, JSON for scripting, idempotency, audit logging on destructive ops) are part of the contract. SOLID, DRY, KISS applied throughout.

When implementation begins, this doc is the spec. Read `llmwiki -h` to know what the user expects to type. Read the mapping table to know which architecture doc owns each command. Read the conventions to know how the CLI should behave.
