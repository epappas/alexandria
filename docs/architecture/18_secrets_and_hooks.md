# 18 — Secrets and Hooks

> **Cites:** `research/reviews/02_mlops_engineer.md` (#7, #8, recommendations on secrets and hooks), `research/reviews/03_ai_engineer.md` (§3.5 concurrent sessions), `12_conversation_capture.md` (conversation mining), `17_observability.md` (log redaction).

## Scope

This doc covers two related but distinct surfaces:

1. **Secrets management** — encrypted storage, headless-server access, rotation, revocation, redaction in logs.
2. **Conversation-capture hooks** — install/uninstall/verify lifecycle, idempotency, non-blocking execution, concurrent session handling.

Both are trust-boundary concerns: they touch user credentials and user conversation data. They do not belong in `16_operations_and_reliability.md` (infrastructure) or `17_observability.md` (logs). They deserve their own doc because getting them wrong silently leaks credentials or corrupts the conversation capture loop — both failure modes are high-impact.

## Part 1 — Secrets management

### What counts as a secret

Every credential used by an adapter or provider:

- GitHub personal access tokens, GitHub App private keys.
- Google OAuth client secrets and refresh tokens (Gmail, Calendar, Drive).
- Slack OAuth tokens (user token, bot token).
- Discord bot tokens.
- Notion integration tokens.
- S3 / GCS / Dropbox API keys and IAM role ARNs.
- IMAP passwords and app passwords.
- Anthropic / OpenAI / Gemini API keys.
- Custom endpoint tokens (self-hosted vLLM / SGLang / LiteLLM).

Every secret is referenced from `config.toml` **by name only**. Values live in `~/.alexandria/secrets/<ref>.enc`.

### On-disk layout

```
~/.alexandria/secrets/
├── _vault.meta.json       # key derivation params, salt, KDF version
├── _audit.jsonl           # audit log: every rotate / reveal / revoke
├── anthropic_key.enc
├── github_pat.enc
├── gcal_refresh_token.enc
├── slack_user_token.enc
└── ...
```

Each `.enc` file is AES-256-GCM encrypted with a per-secret random nonce and a 256-bit key derived from:

1. **Primary:** OS keyring master key (`keyring` package — macOS Keychain, Linux Secret Service / libsecret, Windows Credential Locker).
2. **Fallback A — `ALEXANDRIA_VAULT_PASSPHRASE` env var.** For headless Linux servers, CI, and containers without a keyring service. The passphrase must be entered once per daemon boot; the daemon derives the master key via Argon2id with the parameters in `_vault.meta.json`.
3. **Fallback B — interactive prompt at daemon start.** If neither keyring nor env var is available and the daemon is running under a TTY, prompt. If no TTY is available, the daemon refuses to start with a clear error message.

**The vault meta file:**

```json
{
  "kdf": "argon2id",
  "kdf_version": 1,
  "salt": "<base64>",
  "memory_cost": 65536,
  "time_cost": 3,
  "parallelism": 4,
  "primary_source": "keyring",
  "fallbacks": ["env:ALEXANDRIA_VAULT_PASSPHRASE", "tty_prompt"]
}
```

Never encrypted. Never contains a secret. Safe to commit to a backup.

### The secret record

Each `<ref>.enc` file, when decrypted, is a JSON document:

```json
{
  "ref": "github_pat",
  "type": "token",
  "created_at": "2026-03-01T00:00:00Z",
  "rotated_at": "2026-04-16T12:00:00Z",
  "last_used_at": "2026-04-16T14:20:00Z",
  "value": "ghp_...",
  "metadata": {
    "scopes": ["repo", "read:org"],
    "notes": "personal PAT for @epappas; expires 2026-10-01"
  }
}
```

Only `value` is sensitive; the wrapper fields are kept for audit and UX. The encryption protects the whole file.

### CLI

```
alexandria secrets set <ref> [--from-stdin | --from-file PATH]
alexandria secrets rotate <ref> [--from-stdin | --from-file PATH]
alexandria secrets revoke <ref> [--disable-adapters]
alexandria secrets list                                # ref names, types, last-used, NEVER values
alexandria secrets reveal <ref> [--confirm]            # prints value with confirmation; audit logged
alexandria secrets verify <ref>                        # re-decrypts and does a non-destructive ping
```

### Rotation

```
echo "$NEW_TOKEN" | alexandria secrets rotate github_pat --from-stdin
```

Workflow:

1. Read the current decrypted record (for audit trail).
2. Write the new record with `rotated_at = now()` and the new value.
3. Save the OLD record to `~/.alexandria/secrets/.rotated/<ref>-<timestamp>.enc` — kept for 7 days by default, then gc'd. This lets a user unroll a rotation if the new token turns out to be wrong.
4. Append to `_audit.jsonl`.
5. Signal every running adapter that uses this ref to reload its credential on its next call. No adapter restart is needed because adapters read secrets through a `SecretResolver` that caches with a short TTL (60s).

### Revocation

```
alexandria secrets revoke github_pat --disable-adapters
```

Workflow:

1. Wipe `<ref>.enc` by overwriting with zeros then unlinking.
2. With `--disable-adapters`, mark every adapter referencing this secret as `status = 'auth_required'` in `source_adapters`. The scheduler skips auth-required adapters.
3. Append to `_audit.jsonl`.
4. Log a warning to `daemon-YYYY-MM-DD.jsonl`.
5. Without `--disable-adapters`, adapters using the ref will fail their next call with a clear "secret revoked" error; the circuit breaker from `16_operations_and_reliability.md` opens and the user sees it in `alexandria status`.

### Audit log

`~/.alexandria/secrets/_audit.jsonl`:

```json
{"ts":"2026-04-16T12:00:00Z","event":"rotated","ref":"github_pat","caller":"cli"}
{"ts":"2026-04-16T12:00:30Z","event":"reloaded","ref":"github_pat","caller":"adapter:gh-acme-web"}
{"ts":"2026-04-16T14:15:00Z","event":"revealed","ref":"github_pat","caller":"cli","reason":"user debugging adapter"}
{"ts":"2026-04-16T14:30:00Z","event":"revoked","ref":"slack_user_token","caller":"cli","disable_adapters":true}
```

Every sensitive operation is recorded. The file is append-only; `chattr +a` is recommended on Linux where available.

### Log redaction

**Closes:** mlops #7 tail (tool-call logs leaking tokens).

Every log emitter in `17_observability.md` passes its payload through a `SecretRedactor` before writing:

1. Maintains a set of currently-loaded secret values (sourced from the `SecretResolver` cache, refreshed on every new secret).
2. For every outgoing log line, scans `data` fields (recursively) for exact matches.
3. Replaces matches with `<REDACTED:<ref>>` so the log reader can see which secret was referenced without seeing the value.

This is not perfect — it does not catch base64-encoded, rotated, or derived values — but it catches the most common failure mode (a tool argument containing the raw token). For additional safety, `wiki_log_entries.details` (JSON blob capturing tool-call metadata) is also passed through the redactor before persisting.

### Tool-call argument redaction in the runs table

When the guardian's `write(create, ...)` is invoked with a tool argument that contains a secret (e.g., a user pastes a token into a wiki page), the redactor still runs — but it only catches the exact-match case. This is flagged in the verifier's check set: if a staged wiki page contains a string that matches a known secret, the verifier rejects the run with reason `secret_in_content`. This is an additional defense-in-depth beyond the redactor.

Users are expected to never paste secrets into the wiki. The verifier is the safety net.

## Part 2 — Conversation-capture hooks

Cross-references `12_conversation_capture.md` for the adapter itself. This section covers the **lifecycle** of the hook installation on each supported client, plus the concurrent-session concern from ai-engineer §3.5.

### Supported clients

| Client | Hook events | Install target | Schema |
|---|---|---|---|
| Claude Code | `Stop`, `PreCompact` | `~/.claude/settings.local.json` | Claude Code hook spec |
| Codex CLI | `Stop`, `PreCompact` | `~/.codex/hooks.json` | Codex hook spec |
| Cursor | `SessionEnd`, `ContextLimit` | `~/.cursor/hooks.json` | Cursor hook spec (evolving) |

### CLI

```
alexandria hooks install <client> [--workspace X] [--bin-path <path>]
alexandria hooks uninstall <client>
alexandria hooks verify [<client>]         # check: binary exists, schema match, exec bit set
alexandria hooks list                       # shows all installed hooks across clients
alexandria hooks status                     # last invocation, errors in the last 24h
```

### Install behavior

`alexandria hooks install claude-code --workspace research`:

1. Detect Claude Code version by reading `~/.claude/package.json` (or equivalent). Refuse to install if the version is unknown — the schema may have changed. Emit a clear error with the version found and the supported range.
2. Detect Claude Code's settings file at `~/.claude/settings.local.json`. If the file does not exist, create it with a minimal `{}`.
3. Parse the file as JSON. If unparseable, abort with a clear error: *"your settings file is not valid JSON; fix it first"*.
4. Write (or update) a hook entry wrapped in marker comments:

```json
{
  "hooks": {
    "Stop": [
      {
        "_alexandria_managed": true,
        "_alexandria_version": "1.0",
        "_alexandria_installed_at": "2026-04-16T14:30:00Z",
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/alexandria",
            "args": ["capture", "conversation", "--client", "claude-code", "--workspace", "research", "--detach"],
            "timeout": 30
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "_alexandria_managed": true,
        "_alexandria_version": "1.0",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/alexandria",
            "args": ["capture", "conversation", "--client", "claude-code", "--workspace", "research", "--detach", "--reason", "pre-compact"],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

5. Validate the resulting JSON is still parseable.
6. Record the install in `~/.alexandria/state/hooks.json`: `{client, workspace, installed_at, settings_path, bin_path}`.

The `_alexandria_managed: true` marker is the uninstall handle. **Only blocks with this marker are touched by uninstall.** User-authored hook blocks are never modified.

### Uninstall behavior

`alexandria hooks uninstall claude-code`:

1. Parse the settings file.
2. Remove every hook block where `_alexandria_managed === true`.
3. Write the result back. If there are zero hook blocks left under a key, remove the key itself.
4. Remove the corresponding entry from `~/.alexandria/state/hooks.json`.

The uninstall is a pure JSON operation. No sed, no grep, no line-based edits.

### Verify behavior

`alexandria hooks verify`:

For each installed hook in the state file:

1. Check the settings file exists and parses.
2. Check the marker block is still present (user may have deleted it manually).
3. Check `command -v <bin_path>` resolves — the alexandria binary still exists at the installed path.
4. Check `test -x <bin_path>` — the binary is still executable.
5. Check the client version is still in the supported range.
6. Check the last hook invocation from `hook-*.jsonl` (if any) — did it succeed or fail?

Report per-hook pass/fail with a remediation hint per failure mode.

### Hook script: non-blocking, idempotent, failing silent

The command alexandria registers is:

```
/usr/local/bin/alexandria capture conversation --client <client> --workspace <slug> --detach [--reason pre-compact]
```

Key properties:

1. **`--detach` returns immediately.** The `capture conversation` subcommand spawns a detached subprocess that does the actual mining in the background and returns within ~50ms. Claude Code does not wait on mining.
2. **Missing-binary is silent.** If `/usr/local/bin/alexandria` no longer exists (user uninstalled alexandria without uninstalling hooks), the binary is not invoked — Claude Code logs an error in its own logs but does not block. alexandria's `verify` command surfaces the stale hook the next time the user runs it.
3. **Non-zero exit is silent.** The capture subcommand logs errors to `~/.alexandria/logs/hook-YYYY-MM-DD.jsonl` but returns exit code 0 to Claude Code. Claude Code does not need to know about alexandria's internal failures.
4. **Idempotent on retries.** If Claude Code's Stop hook fires twice for the same session (e.g., the user hit retry), the second invocation sees that the session's transcript is unchanged (same sha256) and returns immediately without re-mining.

### Session-level concurrency — ai-engineer §3.5

**The problem:** multiple Claude Code sessions running concurrently in different terminals, each with its own Stop hook firing on its own schedule. Two sessions in the same workspace may both trigger a capture at the same instant.

**The solution:** per-session serialization via SQLite, per-workspace serialization via the workspace file lock from `16_operations_and_reliability.md`.

New SQLite table:

```sql
CREATE TABLE capture_queue (
  session_id    TEXT PRIMARY KEY,
  workspace     TEXT NOT NULL REFERENCES workspaces(slug),
  client        TEXT NOT NULL,
  transcript_path TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',  -- 'queued'|'in_progress'|'done'|'failed'
  enqueued_at   TEXT NOT NULL,
  started_at    TEXT,
  completed_at  TEXT,
  last_content_hash TEXT,  -- sha256 of the transcript last time we successfully mined it
  error         TEXT
);
```

Workflow on every capture invocation:

1. Compute the transcript's sha256.
2. `INSERT OR IGNORE INTO capture_queue (session_id, ..., last_content_hash) VALUES (?, ..., NULL)`.
3. If the INSERT succeeded (new session), proceed to mine.
4. If the INSERT was ignored (session already in the queue), UPDATE: if `status = done` AND `last_content_hash` equals the new hash, no-op (idempotent re-fire). Otherwise, transition to `queued` and mine.
5. Mining happens in a detached subprocess owned by the daemon. The subprocess acquires the workspace file lock, processes the transcript, commits, releases, updates `capture_queue.status = done`, records `last_content_hash`.
6. If two captures for different sessions in the same workspace race, the second one blocks on the workspace file lock for up to 30 seconds. Past 30 seconds, it fails with `workspace_busy` and retries on the next hook fire.

**No session's capture is ever lost.** Either it is mined, it is queued, or it fails loud and retries.

### Concurrent conversation-capture across 5-10 live sessions

The user the ai-engineer worried about has 5-10 Claude Code sessions across several workspaces. Each session's Stop hook fires independently. Captured behavior:

- Each hook fire enqueues its session in `capture_queue`.
- The daemon's `capture_worker` pool (one worker per workspace) drains the queue per workspace serially.
- Within a workspace, captures process in the order their hooks fired.
- Across workspaces, captures run in parallel (up to the daemon's total worker pool size).
- A stuck capture (frozen subprocess) is detected by the capture_worker heartbeat after 120 seconds and killed; the row is transitioned to `failed` with reason `stuck`.

### Hook binary path

`alexandria hooks install` resolves the binary path in order:

1. `--bin-path` CLI argument if provided.
2. `which alexandria` (the binary currently running the install).
3. The default install paths: `/usr/local/bin/alexandria`, `~/.local/bin/alexandria`.

The resolved path is written into the hook config verbatim. When the user upgrades alexandria to a new path, they run `alexandria hooks install <client> --bin-path <new>` (which overwrites the marker block in place) or `alexandria hooks uninstall` + `alexandria hooks install` in sequence.

### Hook status and metrics

`alexandria hooks status`:

```
$ alexandria hooks status

Claude Code (installed 2026-04-10 14:23, binary /usr/local/bin/alexandria)
  Last invocation:      2026-04-16 14:20 (success, 43ms)
  Captures in 24h:      37
  Failed in 24h:        0
  Pending in queue:     0

Cursor (installed 2026-04-12 09:00, binary /usr/local/bin/alexandria)
  Last invocation:      2026-04-16 11:45 (success, 51ms)
  Captures in 24h:      12
  Failed in 24h:        1  (session vasdf234: transcript too large)
  Pending in queue:     0

Codex CLI (NOT installed)
  Run: alexandria hooks install codex --workspace research
```

## SOLID application

### Secrets

- **Single Responsibility.** `SecretVault` owns encryption/decryption. `SecretResolver` owns caching and lookup by ref. `SecretRotator` owns rotation. `SecretRedactor` owns log redaction. Four classes, four responsibilities.
- **Open/Closed.** New secret types (OAuth refresh flows, certificate bundles) are new `SecretType` entries. The vault format is unchanged.
- **Liskov.** All secret types round-trip through the same encrypt/decrypt primitives. Different usage patterns don't leak into the vault.
- **Interface Segregation.** Adapters depend on `SecretResolver.get(ref)` — one method. They never touch the vault directly, never know about encryption, never see the audit log.
- **Dependency Inversion.** Tests inject a `FakeSecretVault` that stores cleartext in memory. Production injects the real vault. Application code is identical.

### Hooks

- **Single Responsibility.** `HookInstaller` owns schema-specific writes. `HookVerifier` owns checks. `HookRunner` owns the detached spawn. `CaptureQueue` owns concurrency. Four classes.
- **Open/Closed.** New clients add a new `HookInstaller` subclass for their schema. No changes elsewhere.
- **Liskov.** Every installer honors the same interface: `install(client, workspace, bin_path)`, `uninstall(client)`, `verify(client)`.
- **Interface Segregation.** The CLI only depends on the `HookInstaller` protocol. It does not know Claude Code's settings format.
- **Dependency Inversion.** Schema detection is injected; a `ClaudeCodeSchemaV1` and `ClaudeCodeSchemaV2` can coexist.

## DRY notes

- **One vault**, one encryption algorithm, one audit log. No per-secret custom code.
- **One `capture_queue` table** serializes every client's captures. No per-client concurrency logic.
- **One `_alexandria_managed` marker** identifies our hook blocks across every supported client.
- **One `SecretRedactor`** redacts across every log family.

## KISS notes

- Secrets are encrypted JSON files. Audit is JSONL. No KMS, no Vault.
- Hooks are bash-like command entries in each client's settings file. No agent process, no local server for hook dispatch.
- Concurrency is one SQLite table + one advisory file lock. No distributed coordination.
- Rotation is "write new, keep old for 7 days". No version history.

## What this doc does NOT cover

- **Conversation-capture adapter internals** — `12_conversation_capture.md`.
- **Daemon supervision, schema migrations, backup** — `16_operations_and_reliability.md`.
- **Logs, run_id correlation, crash dumps** — `17_observability.md`.
- **Wiki write transactions that captures produce** — `13_hostile_verifier.md`.

## Summary

Secrets live in `~/.alexandria/secrets/*.enc`, AES-256-GCM encrypted with a key derived from the OS keyring (primary), env var (headless fallback), or TTY prompt (last resort). Rotation keeps a 7-day backup of the old value. Revocation wipes the file and disables dependent adapters. Every log line is passed through a redactor that catches exact-match secret values. An audit log records every rotate/reveal/revoke.

Hooks are installed into client-specific settings files with a `_alexandria_managed` marker for safe uninstall. The registered command is `alexandria capture conversation --detach`, which spawns a background subprocess and returns in <50ms — Claude Code never waits on mining. Concurrent captures are serialized by session via SQLite and by workspace via the same file lock from `16_operations_and_reliability.md`. Stale hooks, missing binaries, and client version drift are detected by `alexandria hooks verify`.

Every trust-boundary failure mode the mlops-engineer and ai-engineer flagged has a named mechanism and a CLI command to inspect it.
