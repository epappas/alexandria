# Architecture

Design decisions for `alexandria` — a **single-user, local-first** Python tool that spawns and maintains personal wikis guarded by an LLM agent. One install per user machine. No multi-tenancy. Wikis live on disk under `~/.alexandria/` so the user can back them up, version them, or open them in Obsidian.

Read in order:

| # | Doc | What it answers |
|---|---|---|
| 01 | [Vision and principles](01_vision_and_principles.md) | Why a compiled wiki, not RAG. The three layers. Single-user invariants. |
| 02 | [System architecture](02_system_architecture.md) | CLI-first shape, local daemon, optional web UI, SQLite + filesystem. |
| 03 | [Workspaces and scopes](03_workspaces_and_scopes.md) | Global knowledge vs project/customer workspaces. How scoping works. |
| 04 | [Guardian agent](04_guardian_agent.md) | What the agent knows, can do, and how it stays aware of its own output. |
| 05 | [Sources, sync, and subscriptions](05_source_integrations.md) | Adapters for code, papers, docs, GitHub, gists, Drive/S3/Notion, newsletters, Twitter. |
| 06 | [Data model](06_data_model.md) | On-disk layout + SQLite schema for metadata and search. |
| 07 | [Open questions](07_open_questions.md) | What's deferred. |
| 08 | [MCP integration](08_mcp_integration.md) | Running `alexandria` as an MCP server for Claude Code, Cursor, Codex, Claude Desktop, and HTTP clients. |
| 09 | [Subscriptions and feeds](09_subscriptions_and_feeds.md) | How blogs, Substack, YouTube, newsletters, Mastodon, and Twitter actually get polled, normalized, and surfaced to the agent. The honest platform matrix. |
| 10 | [Event streams](10_event_streams.md) | Continuous ingestion of GitHub / Calendar / Gmail / Slack / Discord / cloud-storage activity into a SQLite event table. Cross-stream correlation via `refs`. Scheduled temporal synthesis into `wiki/timeline/`. |
| 11 | [Inference endpoint](11_inference_endpoint.md) | alexandria is a knowledge engine, not a chat client. Two modes: client-MCP (zero LLM config on our side) and daemon-owned (for unattended scheduled synthesis only). Provider abstraction covers Anthropic / OpenAI / Gemini / any OpenAI-compatible endpoint (Ollama / vLLM / SGLang / LM Studio / LiteLLM proxy). Verified Anthropic prompt caching pricing. |
| 12 | [Conversation capture](12_conversation_capture.md) | Mining the user's own AI sessions (Claude Code / Cursor / Codex / ChatGPT / Slack / markdown) into `raw/conversations/` + `events`. Auto-save hooks on Stop + PreCompact. The closed loop that makes retroactive query actually work. Directly influenced by mempalace (see `research/reference/14_mempalace.md`). |
| 13 | [Hostile verifier and staged writes](13_hostile_verifier.md) | Every wiki write goes through a fresh-context, read-only, hostile-prompted verifier agent before commit. Staged-run transaction is the single mechanism for cascade atomicity, synthesis crash recovery, and budget-stop rollback. The single biggest correctness addition. Closes the `ai-engineer` review's biggest gap. |
| 14 | [Evaluation scaffold](14_evaluation_scaffold.md) | Five metrics (M1 citation fidelity, M2 cascade coverage, M3 retroactive query benchmark, M4 cost characterization, M5 self-consistency) running as a fourth `eval` operation alongside ingest/query/lint. Capability floor for weaker models. Freeze clause: no new sources until M1+M2 are wired up. |
| 15 | [Cascade and convergence policy](15_cascade_and_convergence.md) | When source N contradicts source M: hedge with dated marker, never silently overwrite. Four stage operations (merge, hedge, new_page, cross_ref). Workflow on top of the staging mechanism from doc 13. |
| 16 | [Operations and reliability](16_operations_and_reliability.md) | Daemon as supervised subprocesses (per-child restart policy). Schema migrations framework. Source-runs orphan sweep. Per-provider rate limiter + circuit breakers. `alexandria backup create/restore`. FTS5 integrity verification. Synthesis kill switches. |
| 17 | [Observability](17_observability.md) | Seven log families with `run_id` correlation. `alexandria status --json`. `alexandria logs show <run_id>`. `alexandria doctor`. Crash dumps. No telemetry, no cloud. |
| 18 | [Secrets and hooks](18_secrets_and_hooks.md) | AES-256-GCM secrets vault with OS keyring + headless-server fallback + audit log + rotation/revocation/redaction. Conversation-capture hook lifecycle: install/uninstall/verify per client (Claude Code / Codex / Cursor) with concurrency via `capture_queue` table. |
| 19 | [Belief revision and traceability](19_belief_revision.md) | Beliefs as first-class structured rows with stable identity, supersession history, and provenance chains to verbatim source quotes. The `why` MCP tool answers *"why do I believe X?"* with a full deterministic trace. Closes the user's ask for explainability + revision. |
| 20 | [CLI surface](20_cli_surface.md) | **Implementation contract.** The canonical `alexandria -h` output, command-to-doc mapping, design conventions (single binary, two-tier help, global flags, idempotency, audit logging), important command pairings (`why` vs `synthesize`, `query` vs `why`, `ingest` vs `synthesize`, `runs show` vs `logs show`), and seven follow-up gaps in other docs that must be closed before implementation. |

All research that informs these decisions lives under `docs/research/`. Architectural claims cite specific `research/reference/NN_*.md` files.
