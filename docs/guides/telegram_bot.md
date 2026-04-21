# Telegram bot — chat with your knowledge from anywhere

Make alexandria ubiquitous. Send a message from your phone, watch, or
laptop; an agent running on your always-on machine queries your
knowledge base and replies — with citations, via your Claude
subscription, over Telegram.

## Why this specific shape

- **No public exposure of alexandria.** The bot runs on your desktop;
  only Telegram sees traffic. Your knowledge base never leaves the
  machine.
- **Mobile UX is native and good.** Telegram already handles
  authentication, notifications, message history, voice, photos, and
  files. We don't rebuild any of that.
- **Uses your existing agent.** The bot spawns ``claude -p``, which
  already has the ``mcp__alexandria__*`` tools registered at user scope.
  No new agent logic; the bot is a thin adapter.
- **Auth is trivial.** Allowlist your Telegram user ID in config;
  everyone else gets "you are not on this bot's allowlist."

## Architecture

```
phone / watch / laptop
  ↓ Telegram message
Telegram infrastructure
  ↓ long-poll
alexandria bot (on your always-on machine)
  ↓ spawn `claude -p --model haiku "<question>"` with alexandria MCP
Claude Code agent (reads via alexandria MCP tools)
  ↓ synthesized answer + citations
alexandria bot → Telegram → you
```

Each Telegram message is its own isolated subprocess. No session state
is shared across messages — every question is answered from scratch.
Good for security and simplicity; a minor limitation if you want
multi-turn context.

## One-time setup

### 1. Install the bot extra

```bash
pip install "alexandria-wiki[bot]"
# or with uv:
uv tool install --force "alexandria-wiki[bot]"
```

### 2. Register a Telegram bot

Open Telegram, message [@BotFather](https://t.me/BotFather), run
`/newbot`, follow the prompts. BotFather hands you a token that looks
like `1234567890:AAH...`.

### 3. Find your Telegram user ID

Message [@userinfobot](https://t.me/userinfobot). It replies with a
numeric user ID. Add additional IDs for anyone else who should be able
to message the bot (typically: just you).

### 4. Store the bot token

Either in the alexandria secret vault:

```bash
alxia secrets set telegram_bot_token
# paste the BotFather token when prompted
```

Or in an env var (handy for ephemeral/CI runs):

```bash
export ALEXANDRIA_TELEGRAM_BOT_TOKEN='1234567890:AAH...'
```

The bot prefers the env var if both are set.

### 5. Configure the allowlist + workspace

Edit `~/.alexandria/config.toml`:

```toml
[bot]
telegram_allowlist = [123456789]       # your user ID from step 3
workspace = "global"                    # or a specific workspace slug
model = "haiku"                         # claude -p --model
max_reply_chars = 3500                  # stay under Telegram's 4096 limit
agent_timeout_s = 180
```

The `telegram_token_ref` defaults to `"telegram_bot_token"`, matching
step 4. Override only if you use a different ref.

### 6. Confirm configuration

```bash
alxia bot status
```

You should see `Token: set`, `Allowlist size: 1` (or more), and
`python-telegram-bot installed`.

## Running the bot

### Foreground

```bash
alxia bot start
```

Blocks until Ctrl+C. Useful for first-run testing.

### As a systemd user service (recommended)

Create `~/.config/systemd/user/alexandria-bot.service`:

```ini
[Unit]
Description=alexandria Telegram bot
After=network-online.target

[Service]
Type=simple
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/alxia bot start
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=default.target
```

Enable + start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now alexandria-bot
journalctl --user -u alexandria-bot -f       # follow logs
```

Stop with `systemctl --user stop alexandria-bot`.

## How messages flow, step by step

1. You send a text message to your bot on Telegram.
2. Bot checks `update.effective_user.id` against `telegram_allowlist`.
   Non-allowlisted users get a refusal reply.
3. Bot runs `claude -p --model <X> --append-system-prompt "<alexandria
   orientation>" "<your message>"`.
4. The agent inside that subprocess has access to `mcp__alexandria__*`
   tools from your user-scope MCP registration. It reads the system
   prompt (which tells it to prefer search/grep/read over synthesis),
   picks the right tool chain, produces an answer with citations.
5. Bot reads the agent's stdout, truncates to `max_reply_chars`, and
   sends as a Telegram reply.

## Caveats

### Desktop must be running

If your always-on machine is off, the bot is off. This is "query my
knowledge from my couch" usable, not "query my knowledge from a 14-hour
flight" — for the latter you'd need to ship the knowledge base to the
phone, which is a different project.

### One subprocess per message

Each message starts a fresh `claude -p`. Cold start is a few hundred
milliseconds. Not a problem for chat cadence; watch out if you're
scripting bulk queries.

### Nested subscription calls during ingest

If the agent decides to call `mcp__alexandria__ingest` or
`mcp__alexandria__query`, alexandria internally spawns another
`claude -p` for its LLM work. So that single Telegram message triggers
two nested Claude Code subscription calls. For read-only queries
(search/grep/read/follow/why) no nesting happens. Watch your
rate-limit counters if the bot is used heavily for ingestion.

### No multi-turn context

Each message is answered from scratch. "Follow up on what you just
told me" does not work — the agent has no memory of the previous
message. Works around: include context in the next question, or
accept that Telegram is a Q&A surface, not a chat thread.

### Voice messages aren't supported (yet)

Right now voice messages get a polite refusal. Adding Whisper
transcription would be ~50 lines of code if you want it; open an issue.

### Allowlist is the only auth

There is no per-user capability scoping — anyone on the allowlist can
see everything in the configured workspace. Don't allowlist people you
wouldn't also give shell access to your alexandria data.

### No rate limiting

A compromised allowlisted account could burn your Claude subscription
rate limit quickly. Telegram's own rate limiting helps, but do not
allowlist untrusted accounts.

## Extending

- **Multiple workspaces.** Run one bot per workspace: copy the systemd
  unit, override `--workspace` in `ExecStart`, use a different
  `telegram_token_ref`. Each bot gets its own Telegram handle.
- **Signal / iMessage / Discord.** The agent wrapper lives in
  `alexandria/bot/agent.py` — all you need is another thin adapter
  that calls `ask_agent(question, ...)` and relays the reply.
- **Voice input.** Add a voice handler that transcribes with
  faster-whisper before calling `ask_agent`. The infrastructure is
  already in alexandria's `[all]` deps.
