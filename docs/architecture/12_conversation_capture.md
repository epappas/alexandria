# 12 — Conversation Capture

> **Cites:** `research/raw/36_mempalace.md`, `research/reference/14_mempalace.md` (three adoptions), `research/raw/00_karpathy_tweet.md` ("raw data from a given number of sources is collected").

## Why this doc exists

The user's most important source of gathered knowledge is **their own conversations with AI**. Hours per day in Claude Code, Cursor, Codex, Claude Desktop, Claude.ai, and ChatGPT — thinking out loud, making design decisions, debugging code, reviewing PRs, writing plans. When a session ends, that context evaporates. The next session starts from zero.

llmwiki's promise of retroactive query (invariant #15, `01_vision_and_principles.md`) is **hollow** if the user cannot ask *"what did I decide in yesterday's Claude Code session about the auth refactor"* and get a grounded answer. Closing this loop is the single highest-leverage addition to the knowledge engine.

MemPalace already ships the capture machinery (`research/reference/14_mempalace.md`, Adoption 2 + 3). llmwiki adopts the same pattern, adapted to our model: **conversation transcripts land as markdown documents in `raw/conversations/` and as structured events in the `events` table, with auto-save hooks in the common MCP clients so the loop closes with zero manual effort**.

## Two complementary capture paths

Conversation capture has **two paths**, deliberately complementary so that no session escapes the engine regardless of how the user runs their agent:

1. **File-based capture (post-hoc).** Hooks fire at `Stop` / `PreCompact` events in the connected client. The hook script invokes `llmwiki capture conversation --detach`, which mines the client's transcript file (Claude Code's `~/.claude/projects/*.jsonl`, Cursor's SQLite state DB, Codex's session log, ChatGPT export). This path captures the **full chat including user text and assistant text**, but **only works for clients that support hooks**.
2. **MCP-side capture (real-time).** Whenever a connected MCP client (Claude Code, Cursor, Codex, Claude Desktop, Claude.ai web, Windsurf, Zed, Continue) invokes any of llmwiki's MCP tools, the MCP server **observes the call** and records it. This path captures the **agent's interaction with llmwiki specifically** — every tool call, args (redacted per `18_secrets_and_hooks.md`), result summary, latency — but **does not see the surrounding user/assistant text** because that text never traverses our process boundary. This path **always runs** regardless of client capabilities, including for hookless clients like Claude.ai web.

**Combined**, the two paths give the user:

- Full chat history (file-based, when available) — what was said and decided.
- Tool-call audit trail (MCP-side, always) — what the agent actually did with llmwiki.
- Cross-correlation via session_id — the same session ID appears in both stores, so a `why` query (`19_belief_revision.md`) on a belief written from a Claude Code session can pull both the file-based transcript and the MCP-side audit trail.

Neither path is sufficient alone. Together they close the loop on *"what happened in this session?"* for every supported client.

## The conversation adapter — a hybrid SOURCE + EVENT_STREAM

`05_source_integrations.md` defines four adapter kinds: `SOURCE`, `SUBSCRIPTION`, `EVENT_STREAM`, `STORAGE`. Conversations (file-based path) are a **hybrid SOURCE + EVENT_STREAM**, like the `git-local` adapter in `10_event_streams.md`:

- **As a SOURCE**: each session becomes one markdown document at `raw/conversations/<client>/<yyyy-mm-dd>-<session-id>.md`. Verbatim user + assistant turns, tool calls, and results preserved. The guardian can `read` the file like any other raw source.
- **As an EVENT_STREAM**: each session also emits structured rows into the `events` table — `session_started`, `user_turn`, `assistant_turn`, `tool_call`, `tool_result`, `session_ended`, `session_compacted` — tagged with client name, session id, and the markdown file path via `refs`. The guardian can query via `events(source="conversation", client="claude-code", since="7d")` or `grep` over the structured side.

The duality matters: the **document** is what the guardian reads when it needs context for compilation; the **events** are what the guardian queries for temporal questions like *"what did I work on last week?"*.

## MCP-side capture — the always-on observer

The MCP server (`08_mcp_integration.md`) sees every tool call from every connected client. When a Claude Code session calls `read("/wiki/topics/auth.md")`, the MCP server logs the call with the requesting client's identifier, the session ID (from MCP transport), and the response metadata. This logging already exists in `~/.llmwiki/logs/mcp-YYYY-MM-DD.jsonl` per `17_observability.md` — the conversation-capture extension materializes the same data into a **structured SQLite view** that the guardian can query.

### What the MCP server captures per call

| Field | Source | Notes |
|---|---|---|
| `session_id` | MCP transport metadata | Stable per client connection. For stdio mode, this is a daemon-assigned UUID. For HTTP, it comes from the OAuth session. |
| `client_name` | MCP capability negotiation | `claude-code` / `cursor` / `codex` / `claude-desktop` / `claude-web` / `windsurf` / `zed` / `continue` / `unknown`. |
| `client_version` | Same | If the client advertises it. |
| `caller_model` | Same (best-effort) | The model the client is running, when advertised. Used by the capability floor in `14_evaluation_scaffold.md`. |
| `tool_name` | The MCP call itself | `guide` / `list` / `grep` / `search` / `read` / `write` / etc. |
| `redacted_args` | The tool args, post-redaction | Secrets-redacted via `SecretRedactor` from `18_secrets_and_hooks.md` before storage. |
| `tool_args_hash` | sha256 of redacted args | For dedup and run correlation. |
| `result_size_bytes` | Response payload size | For cost/latency analysis. |
| `latency_ms` | Tool execution time | For performance debugging. |
| `run_id` | When the call triggered a staged run | NULL for read-only calls. |
| `result_summary` | One-line summary | Auto-generated from the response (e.g., *"read 3 pages, 14k chars"*). |
| `ts` | Timestamp | ISO 8601 with millisecond precision. |

This data goes into a new SQLite table `mcp_session_log` (defined in `06_data_model.md`) on every call. The on-disk source remains the JSONL log family from `17_observability.md`; the table is the queryable view, populated by an insert at log emission time.

### What the MCP server does NOT capture

- **User text messages.** Those go from the user's keyboard to the LLM directly. They do not traverse llmwiki.
- **LLM text responses.** Same. The LLM responds to the user; only its tool calls are routed through llmwiki.
- **Reasoning traces / thinking blocks.** Same.
- **Other MCP servers' tool calls.** Each MCP server only sees its own surface.

This is **why MCP-side capture is complementary, not a replacement.** For full transcript fidelity (including the user text), the file-based path is required. For an audit trail of the agent's interaction with llmwiki specifically, MCP-side capture is sufficient and always available.

### How the two paths interact

When both paths capture the same session, they reconcile via `session_id`:

1. The MCP-side path emits rows into `mcp_session_log` in real time as the session unfolds.
2. The file-based hook fires at Stop/PreCompact and mines the client's transcript file. This produces a markdown document in `raw/conversations/<client>/...` and a set of `events` rows for the conversation turns.
3. Both stores share the same `session_id`. A `why` query that surfaces the session in either store can join the other.
4. Dedup: re-running file-based mining is idempotent (sha256 of the transcript). Re-running MCP-side capture cannot duplicate because every call has a unique timestamp + tool_args_hash.

For clients **without hook support** (Claude.ai web — no local transcript file, no Stop hook), the MCP-side path is the only capture available. The user still gets:

- Every tool call the agent made via `mcp_session_log`.
- Every page the agent read, with timestamps.
- Every write the agent staged, via the `runs` table.
- Every belief the agent asserted or superseded, via `wiki_beliefs.asserted_in_run`.

The full chat text is missing, but the **agent's interaction with llmwiki** is fully captured. This is enough to answer *"what did this session do to my wiki?"* even without the surrounding chat.

### Querying MCP-side capture

The `events` MCP tool from `10_event_streams.md` gains a new `source = 'mcp_session'` event type so the guardian can query MCP-side captures uniformly with file-based events:

```
events(workspace="research", source="mcp_session", client="claude-web", since="7d")
```

Returns the recent tool calls from Claude.ai web sessions on the research workspace. Combined with the file-based events from clients that support hooks, the agent has a complete picture of every session that touched the workspace in the last week.

### Privacy

The MCP-side log is local-only, like every other log family in `17_observability.md`. Tool args are redacted for secrets via `SecretRedactor`. Result content is summarized to a single line, never stored verbatim — the verbatim content lives in the wiki/raw layers where it belongs, not duplicated in the audit log.

The user can purge MCP-side captures with `llmwiki captures purge --source mcp_session --before <date>`.

## Format detectors

Five format detectors at MVP, each decoupled from the adapter core and registered into a `FormatRegistry`:

### 1. `claude-code` — Claude Code JSONL transcripts

Claude Code stores sessions at `~/.claude/projects/<project-hash>/*.jsonl`. Each line is a JSON object with a `type` field (`user`, `assistant`, `summary`, `system`), a `message` object with `role` and `content`, `uuid`, `sessionId`, `timestamp`, and a `cwd` field that names the project directory.

Detection: file extension `.jsonl` + first line parses as JSON + keys include `sessionId` and `uuid`. Normalizer extracts user turns, assistant turns, tool_use blocks, and tool_result blocks in order, emits them as markdown:

```markdown
# Session <session-id>
> **Project:** <project-directory-name>
> **Client:** claude-code
> **Started:** 2026-04-15T09:00:00Z
> **Ended:** 2026-04-15T11:23:00Z
> **Turns:** 47

## [2026-04-15T09:00:00Z] user

How should we handle the auth refactor?

## [2026-04-15T09:00:12Z] assistant

Let me look at the current auth module first.

[tool_use: Read auth/middleware.py]
[tool_result: <truncated-N-lines>]

...
```

### 2. `cursor` — Cursor session state

Cursor stores sessions in its local app data directory (`~/Library/Application Support/Cursor/User/workspaceStorage/.../state.vscdb` on macOS). The schema is SQLite with a `ItemTable` containing serialized chat objects. Detection is by path; extraction pulls the relevant rows and reconstructs turns.

We read the SQLite file read-only, extract the conversation, normalize into the same markdown schema as claude-code. Cursor does not expose session IDs in a stable way; we synthesize a session id from `(workspace_hash, start_time)`.

### 3. `codex` — OpenAI Codex CLI session logs

Codex CLI writes sessions to `~/.codex/sessions/*.jsonl` (or similar — path is configurable). Schema is close enough to Claude Code's JSONL that the same parser with a detector swap handles it.

### 4. `chatgpt-export` — ChatGPT conversations export

The "Export data" flow in ChatGPT produces a `conversations.json` file with an array of conversation objects, each with a `mapping` dict of message nodes linked by `parent` / `children`. We walk the tree in order, emit markdown.

### 5. `markdown` + `plaintext` — generic fallback

Markdown files with `>` quoted user turns (the common notation for dialogs) get the exchange-pair chunker treatment mempalace uses. Plain text files with obvious `User:` / `Assistant:` patterns or simply alternating paragraphs get a best-effort extraction. These are the escape hatches for anything our structured detectors miss.

### Beyond MVP

Slack workspace exports, Discord server exports, Telegram exports — all follow the same pattern (detect, normalize, emit). Filed as roadmap; the registry pattern makes adding each one a localized change.

## The event schema for conversations

Rows in the `events` table (from `06_data_model.md`):

```
source       = 'conversation'
event_type   ∈ {'session_started', 'user_turn', 'assistant_turn',
                'tool_call', 'tool_result', 'session_ended', 'session_compacted'}
external_id  = '<client>:<session-id>:<turn-index>'     # unique per turn
occurred_at  = message timestamp
actor        = 'user' | '<client>' | 'tool:<tool-name>'
subject      = first 200 chars of the content
body         = full content (for user/assistant turns)
refs         = JSON array including: ['conversation:<session-id>', '<client>',
                                       <any PR/issue/commit refs extracted
                                       from the content>]
payload      = the raw message JSON for round-tripping
```

The `refs` extraction pulls the same identifiers we extract from git commits and Slack messages: `#123`, commit SHAs, PR URLs, issue references. This means a query like `events(refs_contains="#847")` finds **every place PR #847 was discussed** — the GitHub webhook event, the Slack thread, AND the Claude Code conversation where the user asked for help with it. Cross-stream correlation already works — conversations just become another stream with the same correlation key shape.

## Incremental mining — SHA-based, no re-read

Mining a transcript directory is idempotent via content hashing (the same mechanism atomicmemory's compiler uses, from `research/reference/04_atomicmemory_compiler.md`):

1. For each file in the scan:
   - Compute SHA-256 over the raw bytes.
   - Lookup `documents.content_hash` for `path = <file-path>`.
   - Unchanged → skip.
   - Changed or new → parse, normalize, upsert the markdown document, replace the events rows for that session.
2. Claude Code writes to its JSONL files **append-only** during a live session. Our parser handles partial reads by tracking the last-parsed line offset per session; on re-scan, we parse only the tail.
3. Large files (> 10 MB, same default as mempalace's `MAX_FILE_SIZE`) are capped with a warning in the logs, not silently dropped.

`llmwiki mine conversations --workspace <slug>` is the CLI entry point. Same verb as `mempalace mine`, different internals.

## Privacy — conversation data is the most sensitive class

Two rules from invariant #1 (single user) and #9 (vault separation) apply with force:

1. **Never leaves the machine.** Conversations contain the user's private thinking, private work, private discussions with clients and colleagues. llmwiki stores them locally in the user's workspace directory. Zero outbound network for conversation content. Zero telemetry.
2. **Per-workspace routing with explicit defaults.** Conversations do not land in the `global` workspace by default. The user configures which client sessions route to which workspace, typically by matching on the project directory name in the transcript's `cwd` field. For example:

```toml
[[event_streams.conversations]]
type = "conversation"
client = "claude-code"
source_dir = "~/.claude/projects/"
# Route rules evaluated in order; first match wins
[[event_streams.conversations.routes]]
match_cwd = "~/work/acme/**"
workspace = "customer-acme"
[[event_streams.conversations.routes]]
match_cwd = "~/code/research/**"
workspace = "research"
[[event_streams.conversations.routes]]
match_default = true
workspace = "global"
```

The default route (`match_default = true`) is the fallback. If the user wants sessions from `~/private/` to never be captured, they add a route with `skip = true` before the default. Inclusion is explicit; exclusion is also explicit.

3. **Redaction hooks.** An optional pre-write redactor strips strings matching configured patterns (API keys, passwords, PII) from both the markdown document and the events body. Patterns are per-workspace. Implemented as a straightforward regex pass with a `redacted` count in the log. **Not a security boundary** — users should already keep secrets out of their chat sessions — but a useful hygiene layer.

4. **No secrets in events.** Tool arguments are preserved in the `tool_call` event body, which can contain API keys or sensitive file paths. We apply the same redactor pass to tool calls. The full tool result (file contents, command output) lives in the markdown document; it is not duplicated in the event row.

## How conversation captures interact with the staged-write transaction

**Closes:** the per-write commit semantics for capture jobs.

Conversation captures are **not** wiki writes. The conversation transcript lands directly in the document layer at `raw/conversations/<client>/<yyyy-mm-dd>-<session-id>.md` via the same source-adapter machinery used by every other source. Structured turn events land in the `events` table per `06_data_model.md`. Neither path involves the hostile verifier from `13_hostile_verifier.md` because **raw layer writes are not subject to verification** — only the wiki layer is.

When the user later asks the guardian to compile recent conversations into wiki pages (an explicit ingest operation), **that** ingest goes through the full staged-write + verifier + belief-extraction protocol like any other ingest. The capture loop and the synthesis loop are separated by design: capture is cheap, fast, automated, and unverified; synthesis is expensive, slower, opt-in, and verified.

## Auto-save hooks — the three common clients

The hooks are small bash scripts that fire on client-specific events and kick off `llmwiki mine conversations` in the background. They never block the user's workflow and never produce chat-window output in silent mode. Three clients shipped at MVP:

### Claude Code — Stop + PreCompact

Installed by `llmwiki hooks install claude-code`. Writes to `~/.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "~/.llmwiki/hooks/claude-code-stop.sh",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "~/.llmwiki/hooks/claude-code-precompact.sh",
        "timeout": 30
      }]
    }]
  }
}
```

The `stop.sh` script:
1. Reads JSON on stdin (`session_id`, `stop_hook_active`, `transcript_path`).
2. Honors `stop_hook_active` — returns `{}` immediately if set, preventing infinite loops.
3. Counts human messages since last save in `~/.llmwiki/state/hooks/claude-code/<session_id>.last_save`.
4. If the count is ≥ `LLMWIKI_SAVE_INTERVAL` (default 15), updates the state file and launches `llmwiki mine conversations --path "$(dirname $transcript_path)" --detach`.
5. Returns `{}` (silent mode) — no blocking, no chat-window output.
6. `LLMWIKI_VERBOSE=1` enables a blocking-with-reason mode for developers who want to see the save happen.

The `precompact.sh` script is simpler — it always triggers a mine regardless of counter state, because compaction is a one-shot emergency save opportunity.

Both scripts are bounded at ~100 lines. They do no logic that can't be reproduced on the command line; the heavy lifting is `llmwiki mine conversations`.

### Cursor — onSessionEnd + onContextLimit

Cursor's hook system is still evolving. The install target is `~/.cursor/hooks.json` with events `SessionEnd` (equivalent to Claude Code's Stop) and `ContextLimit` (equivalent to PreCompact). Script contents are the same bash logic with a different input JSON parse — Cursor passes workspace hash and session path, which we use to locate the SQLite state DB for extraction.

### Codex CLI — Stop + PreCompact

Codex CLI supports hooks in `~/.codex/hooks.json` with the same `Stop` / `PreCompact` shape as Claude Code. The install target and JSON are a thin variant of the Claude Code installer; the script is shared.

### Install / uninstall commands

The hook lifecycle (install, uninstall, verify, list, status), the concurrent-session serialization via the `capture_queue` table, the binary-existence safety check, the schema detection, and the non-blocking detached subprocess shape are all defined in detail in `18_secrets_and_hooks.md`. That doc is the canonical source for everything related to hook lifecycle and the trust boundary between llmwiki and the connected client.

The summary:

```bash
llmwiki hooks install claude-code [--workspace X]   # writes the settings block, marker-tagged for safe uninstall
llmwiki hooks install cursor
llmwiki hooks install codex
llmwiki hooks install --all                          # installs everywhere detected

llmwiki hooks uninstall claude-code                  # removes ONLY blocks with the llmwiki-managed marker
llmwiki hooks verify [<client>]                      # checks binary path, schema, exec bit
llmwiki hooks list                                    # all installed hooks across clients
llmwiki hooks status                                  # last invocation, errors in 24h, capture_queue depth
```

Idempotent. Marker-tagged. Non-blocking via `--detach`. Concurrent sessions serialized by SQLite. See `18_secrets_and_hooks.md` for the full design.

## The closed loop — what this gives the user

With conversation capture + auto-save hooks enabled on a workspace:

1. **Day 1**: user installs llmwiki, creates a workspace, installs Claude Code hooks pointing at the workspace.
2. **Day 1 onward**: every Claude Code session the user runs gets captured to `raw/conversations/claude-code/<date>-<session>.md` and emits events into the `events` table. Zero manual action required. Zero chat-window clutter.
3. **Day 7**: the daemon's scheduled weekly synthesis (`10_event_streams.md`) fires. The guardian reads the week's conversation events and GitHub events and Slack events and calendar events, compiles a `wiki/timeline/<week>.md` digest, updates `wiki/entities/<active-project>.md` with recent activity, and logs the operation. The user wakes up Monday and has a narrative of last week's work without touching anything.
4. **Day 30**: the user (in Claude Code) asks *"we decided something about auth two weeks ago — what was it?"*. The guardian:
   - `events(source="conversation", refs_contains="auth", since="30d")` → finds the sessions that discussed auth.
   - `read` the relevant session transcripts.
   - `events(source="github", refs_contains="auth", since="30d")` → finds the matching commits + PRs.
   - `read("wiki/concepts/auth-architecture.md")` → the already-synthesized page.
   - Synthesizes a grounded answer with citations to the specific conversation, the PR, and the wiki page.
5. **Day 180**: the user changes projects. The knowledge engine holds six months of compiled wiki, six months of raw conversations, six months of event streams, six months of weekly digests. Retroactive query works cleanly because the raw material was captured in real time and the synthesis ran in the background.

**This is the retroactive query capability of invariant #15 actually working.** Without the conversation adapter and hooks, the user's own thinking is absent from the engine. With them, it's the richest source in the workspace.

## What this doc does NOT cover

- **Live streaming capture.** Watching a transcript file grow while a session is live and reacting to turns as they land. Technically possible via `inotify` / `FSEvents`, but the Stop + PreCompact hooks already capture everything with a bounded delay. Deferred to v2.
- **Cross-session entity resolution.** When two sessions discuss the same concept, merging them into a single wiki entity happens via the normal ingest workflow (the guardian reads both transcripts during its next synthesis run). No dedicated resolver.
- **Multi-user conversations.** Single-user invariant #1 means shared chats (e.g., a Slack thread with multiple humans) go through the `slack` event stream, not the conversation adapter. The conversation adapter is strictly for the user's own AI sessions.
- **Voice transcripts.** If Whisper or a similar tool produces a markdown transcript, it lands via the `markdown` format detector. We do not ship an STT pipeline.

## Open questions specific to conversation capture

1. **Claude.ai web sessions.** Browser-only sessions have no local transcript file to mine. Options: a browser extension that dumps the current conversation on user command, or manual "export and paste" via the `llmwiki paste conversation` CLI. Browser extension is the better UX but non-trivial; filed for v2.
2. **Retention policy.** Do we delete old raw conversation files after the guardian has compiled them into wiki pages? No — the raw layer is immutable (invariant #2). Users who want to reclaim disk run `llmwiki raw archive --older-than 1y --source conversations` to compress into tarballs. Not an MVP feature.
3. **Pre-compile summarization.** Mempalace's hook blocks the AI and asks it to write a diary entry *inside the session* before the transcript is captured. Should we do the same? No — our compilation happens in the background during scheduled synthesis, so the session transcript is the source and the summary is derived from it. Blocking the AI in-session contradicts our "background everything" principle.
4. **Tool-call redaction defaults.** Tool calls contain file paths, command arguments, sometimes API keys. Default redaction should strip obvious secrets (`sk-...`, `ghp_...`, `-----BEGIN PRIVATE KEY-----` blocks) but leave file paths and command output alone. Configurable per workspace. Ship with a conservative default pattern set.

## Summary

Conversation capture is llmwiki's answer to "the user's own thinking-with-AI is the richest source in the knowledge engine, and it's being lost every time a session ends." A new `conversation` adapter mines Claude Code / Cursor / Codex / ChatGPT / markdown transcripts into both the document layer (one markdown file per session in `raw/conversations/`) and the event layer (structured turn/tool-call events with cross-stream `refs`). Auto-save hooks on Stop + PreCompact events in the three major clients close the loop without any manual user action. Privacy is handled by per-workspace routing rules (with an explicit default and skip patterns) and a pre-write redaction pass for secrets. The result is that day-180 retroactive queries actually find the thinking that led to today's state — which is the whole point of the engine.
