# 11 — Inference Endpoint

> **Cites:** `research/raw/35_anthropic_prompt_caching.md`, `research/reference/12_agentic_retrieval.md`, `architecture/10_event_streams.md`, `architecture/07_open_questions.md` A.

## alexandria is a knowledge engine, not a chat client

**alexandria does not host conversations.** Long interactive sessions happen in **connected MCP agents** — Claude Code, Cursor, Claude.ai, Codex, Windsurf, Claude Desktop, Zed, Continue. Those clients run the LLM, manage context, stream responses, handle user input. alexandria exposes tools to them over MCP (see `08_mcp_integration.md`) and otherwise stays out of the way. In this primary mode, **alexandria has no inference endpoint at all** — zero LLM config, zero provider setup, zero API keys required from alexandria's side.

This is the load-bearing design choice: alexandria is a **knowledge engine**. It stores, indexes, retrieves, compiles, and maintains knowledge. It exposes that knowledge through a precise tool surface that any MCP-capable agent can use. The agent provides the reasoning loop; alexandria provides the ground truth and the primitives to navigate it.

## The one case where alexandria owns the loop

There is exactly one mode where alexandria itself needs to drive an agent loop: **unattended background work**. The daemon runs operations when no client is connected, and those operations need to call an LLM directly:

- **Scheduled temporal synthesis** — weekly digest of event streams into `wiki/timeline/<period>.md` (`10_event_streams.md`). No user in the loop at 6am Sunday when the cron fires.
- **Scheduled lint** — periodic health checks, broken-link auto-fixes, stale-citation detection.
- **One-shot batch CLI operations** — `alexandria synthesize --workspace X` run from the command line to trigger a synthesis outside the cron schedule, or `alexandria lint --run --workspace X`. The user invokes the command but does not hold an open chat session; alexandria runs the loop to completion and writes the results.

In each case alexandria runs a bounded, budgeted, opt-in agent loop against a configured inference endpoint, writes the output to the workspace, logs the cost, and exits. It is not interactive. There is no REPL. There is no streaming output to a terminal user.

This is the **only** reason alexandria needs a provider configuration. Every other path — every user question, every user-initiated ingest, every wiki edit happening in a chat — goes through the client's own inference via MCP.

## Two inference modes

| Mode | LLM runs in | alexandria config needed | When |
|---|---|---|---|
| **Client MCP** (default) | Client (Claude Code / Claude.ai / Cursor / Codex / Windsurf / Claude Desktop) | None | All interactive work. The overwhelming majority of use. |
| **Daemon-owned** (scheduled synthesis, scheduled lint, CLI batch ops) | alexandria (via provider SDK) | Yes — provider, model, API key, budget caps | Unattended background / batch operations only. |

The Client MCP mode is a stateless relationship: alexandria does not care which model or provider the client is using, does not see the client's API keys, does not count tokens on behalf of the client. The client pays for its own inference. alexandria is indifferent.

The Daemon-owned mode is the only place provider configuration matters. Everything below is about this mode.

## The provider interface

One abstract contract, multiple implementations. Typed, async, streaming-capable, tool-use-aware.

```python
from typing import Protocol, AsyncIterator
from pydantic import BaseModel

class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict                    # JSON schema for arguments
    cache_hint: bool = False              # set on the LAST tool to cache the whole tools array

class Message(BaseModel):
    role: str                             # "user" | "assistant" | "tool_result"
    content: list[dict]                   # blocks: text | tool_use | tool_result | image
    cache_hint: bool = False              # set on the last static block

class CompletionRequest(BaseModel):
    model: str                            # provider-specific model ID, resolved from preset
    system: list[dict]                    # system blocks (SKILL.md, schema, orientation)
    tools: list[ToolDefinition]
    messages: list[Message]
    max_output_tokens: int
    stop_sequences: list[str] = []
    temperature: float | None = None

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usd_estimate: float                   # computed post-hoc from the provider price table

class CompletionResult(BaseModel):
    content: list[dict]                   # assistant blocks
    stop_reason: str                      # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"
    usage: Usage
    tool_calls: list[dict]                # parsed tool_use blocks

class LLMProvider(Protocol):
    name: str                             # "anthropic" | "openai" | "gemini" | "openai-compatible"

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...

    async def stream(self, req: CompletionRequest) -> AsyncIterator[dict]: ...
    # yields delta events; used by `alexandria chat` for live rendering

    def estimate_cost(self, req: CompletionRequest) -> float: ...
    # pre-flight estimate from the price table and tokenizer — used for dry-run
```

Every provider implementation handles its own API quirks (message format, streaming chunks, tool-use serialization), but the caller side stays uniform.

## Supported providers at MVP

### 1. `anthropic` — first-class

Uses the `anthropic` Python SDK against the Messages API. Supports:
- Tool use via the native `tools` parameter.
- Prompt caching via `cache_control: {"type": "ephemeral"}` on `tools`, `system`, and `messages` blocks (see "Prompt caching" below).
- Streaming via `client.messages.stream(...)`.
- Extended thinking for complex workflows (`thinking: {"type": "enabled", "budget_tokens": N}`) — off by default, toggled per preset.

Why first-class: the whole architecture (`04_guardian_agent.md`, `research/reference/12_agentic_retrieval.md`) is modelled on Claude's agent loop. Prompt caching is load-bearing for cost. Tool use is the cleanest in the industry. If a user picks any provider, Claude is the default.

### 2. `openai` — o-series and GPT

Uses the `openai` Python SDK. Supports:
- Tool use via `tools` parameter on chat completions / responses API.
- Automatic prompt caching (no explicit `cache_control` — OpenAI caches repeated prefixes automatically on requests over a threshold, with no API surface for it).
- Streaming via `stream=True`.
- Reasoning effort (`reasoning_effort: low|medium|high`) for o-series models.

### 3. `gemini` — Google

Uses the `google-genai` SDK. Supports:
- Function calling (function-call block format; maps to our `tool_use` internally).
- Context caching via a separate `CachedContent` resource (different shape from Anthropic but serves the same purpose).
- Streaming.
- Long context (2M tokens on Gemini 2.5 Pro).

### 4. `openai-compatible` — custom endpoints, local or remote

This is the load-bearing escape hatch. Any inference stack that speaks the OpenAI Chat Completions / Responses API works with alexandria behind this one provider. The user points the preset at their endpoint URL and alexandria does not care what is on the other end.

**Confirmed supported (MVP):**

- **Ollama** — `http://localhost:11434/v1`. Easy local deploy, huge model catalog, runs on laptops.
- **vLLM** — `http://<host>:8000/v1`. Production-grade serving with paged-attention KV cache, the canonical high-throughput open-weight stack. `vllm serve <model>` or `python -m vllm.entrypoints.openai.api_server ...`.
- **SGLang** — `http://<host>:30000/v1`. High-performance runtime with structured output support, RadixAttention for prefix sharing (native cache reuse — matches our caching strategy for free), better throughput on complex decoding paths than vLLM for some workloads.
- **LM Studio** — `http://localhost:1234/v1`. Desktop app, good for Mac users with Metal acceleration.
- **llama.cpp server** — `./llama-server --host 0.0.0.0 --port 8080 --api-key ""`. CPU-friendly, runs on Raspberry Pi through to Threadripper.
- **Text Generation Inference (TGI)** from HuggingFace — `http://<host>:8080/v1`. Production option used by HF Spaces.
- **LiteLLM proxy** — a unified gateway that re-exposes ~100 providers (Together, Fireworks, Groq, OpenRouter, DeepInfra, Cohere, AWS Bedrock, Azure OpenAI, and more) as a single OpenAI-compatible endpoint. Run it as `litellm --config config.yaml` and point alexandria at it to access any provider without adding a new adapter to alexandria itself.

**Configuration is identical across all of them:**

```toml
[llm.presets.my-vllm]
provider = "openai-compatible"
endpoint = "http://gpu-box.local:8000/v1"
model = "Qwen/Qwen2.5-72B-Instruct"
max_output_tokens = 4096
# api_key_ref optional — only set if the endpoint requires auth

[llm.presets.my-sglang]
provider = "openai-compatible"
endpoint = "http://gpu-box.local:30000/v1"
model = "meta-llama/Llama-3.3-70B-Instruct"
max_output_tokens = 4096

[llm.presets.my-ollama]
provider = "openai-compatible"
endpoint = "http://localhost:11434/v1"
model = "llama3.3:70b"
max_output_tokens = 4096

[llm.presets.chatgpt]
provider = "openai"
model = "gpt-5"
max_output_tokens = 4096
api_key_ref = "openai_key"
# uses ChatGPT subscription via API key, not the chatgpt.com session

[llm.presets.claude-subscription]
provider = "anthropic"
model = "claude-opus-4-6"
max_output_tokens = 8192
api_key_ref = "anthropic_key"
prompt_cache_ttl = "5m"
# uses Claude API subscription via API key
```

**Tool use** on custom endpoints depends on the underlying model. Llama 3.3, Qwen 2.5, DeepSeek V3, Mistral Large, and most recent open-weight 30B+ models implement OpenAI-style tool calling well. Smaller or older models often don't. The provider wrapper detects tool-use capability from a one-shot probe (`alexandria llm test <preset>` sends a trivial tool-use request and reports pass/fail) and falls back to a system-prompt-based JSON-parsing emulation layer when native tool calling is unavailable.

**Prompt caching** on custom endpoints: paid caching in the Anthropic sense doesn't exist for local/self-hosted stacks, but **KV cache reuse happens automatically** in vLLM, SGLang (via RadixAttention), and llama.cpp server whenever the prefix matches. Our structural discipline — stable `tools` first, stable `system` next, dynamic `messages` last — pays off for free: the local serving stack skips re-computation on the matching prefix and latency drops dramatically on cache hits, with no config needed.

**No telemetry to a third party.** When pointed at a local endpoint, alexandria makes zero outbound calls beyond the configured URL. Privacy-maximalist setups (fully offline with a self-hosted vLLM/SGLang cluster) are first-class.

### Explicitly not at MVP

- **AWS Bedrock / GCP Vertex routing for Anthropic** — same Messages API shape, different auth + endpoint. A config setting on the `anthropic` provider, not a separate provider. Add when a user asks.
- **Azure OpenAI** — same story for `openai`.
- **Together.ai / Fireworks / Groq / OpenRouter / DeepInfra** — all OpenAI-compatible, already covered by the escape hatch.

## Configuration — presets in `config.toml`

Users define named presets and route each operation to a preset. Presets are reusable across workspaces; routing can be overridden per workspace.

```toml
[llm]
default = "claude-opus"

[llm.presets.claude-opus]
provider = "anthropic"
model = "claude-opus-4-6"
max_output_tokens = 8192
api_key_ref = "anthropic_key"           # points to ~/.alexandria/secrets/anthropic_key.enc
prompt_cache_ttl = "5m"                 # or "1h"
thinking = "off"                         # or "low" | "medium" | "high"

[llm.presets.claude-sonnet]
provider = "anthropic"
model = "claude-sonnet-4-6"
max_output_tokens = 4096
api_key_ref = "anthropic_key"
prompt_cache_ttl = "5m"

[llm.presets.gpt-o]
provider = "openai"
model = "o3-mini"
max_output_tokens = 4096
api_key_ref = "openai_key"
reasoning_effort = "medium"

[llm.presets.local-llama]
provider = "openai-compatible"
endpoint = "http://localhost:11434/v1"
model = "llama3.3:70b"
max_output_tokens = 4096
# no api_key_ref — local endpoints don't need one

[llm.routing]
# Only daemon-owned operations appear here. Interactive work happens in the MCP client.
scheduled_synthesis = "claude-sonnet"    # cheaper for routine weekly runs
scheduled_lint      = "claude-sonnet"    # routine health checks
batch_synthesize    = "claude-opus"      # higher quality for CLI-driven one-shots
batch_lint          = "claude-sonnet"
# anything not listed falls back to `llm.default`
```

Per-workspace override in `workspaces/<slug>/config.toml`:

```toml
[llm.routing]
scheduled_synthesis = "local-llama"     # this workspace runs local for privacy
```

The CLI exposes `alexandria llm list`, `alexandria llm add <preset>`, `alexandria llm test <preset>` (sends a trivial ping to verify credentials + endpoint), and `alexandria llm cost <preset> --last 30d` (prints recent usage from the telemetry log).

## Caching honesty: interactive path benefits, daemon path does not

**Closes:** `research/reviews/01_llm_architect.md` §2.5 (cache TTL honesty + cost arithmetic).

alexandria has two LLM-call paths and they have **opposite caching profiles**. Both paths structure their prefixes identically, but only one of them sees real caching wins. The doc must say so:

### Interactive path through MCP — cache-benefiting

The connected client (Claude Code / Cursor / etc.) makes many calls per session, often within seconds of each other. Anthropic's 5-minute default TTL is well within session length. The stable `tools` + `system` prefix (which on the client side includes the MCP tool schemas + the cached alexandria `guide()` response from `04_guardian_agent.md`'s tiered wake-up) hits the cache on every call after the first. **Real-world savings:** ~90% off input cost on the cached portion for the duration of the session. This is the marketing number from `research/raw/35_anthropic_prompt_caching.md` and it is correct for this path.

alexandria itself does not control the client's caching — the client constructs its own prompts. alexandria's job here is to keep its `guide()` output **stable enough to be cacheable**, which the L0/L1 split in `04_guardian_agent.md` enforces by separating stable identity content (L0) from dynamic state (L1) and capping both with hard output-token budgets.

### Daemon-owned path — cache-neutral but prefix-structured for consistency

Scheduled synthesis runs once a week. Lint runs once a day. Eval runs vary (M1/M2 weekly, M3 monthly). **None of these cadences fit Anthropic's 5-minute default TTL.** The daemon path effectively pays cache-write costs (1.25× base) on every run with **zero subsequent reads** before the cache expires.

**The honest number for the daemon path:** prompt caching saves nothing. We still structure prefixes the same way (`tools → system → messages` with stable content first) for two reasons:

1. **Code DRY.** Both paths use the same provider abstraction. Special-casing the daemon would mean two prompt-construction code paths.
2. **1-hour cache opt-in for back-to-back runs.** When a user manually triggers `alexandria synthesize --workspace X` followed within 30 minutes by `alexandria synthesize --workspace Y`, the 1-hour cache TTL (`prompt_cache_ttl = "1h"` in the preset config — see `[llm.presets]` below) does pay off because the second run's tool/system prefix matches the first if both use the same guardian schema. Default is 5m to avoid the 2× write cost when this case is rare.

The cost arithmetic in `11_inference_endpoint.md` previously implied 90% savings for both paths. **Updated:** interactive path sees the savings; daemon path does not (set `prompt_cache_ttl = "1h"` per preset only when the user expects multiple back-to-back runs within an hour). The `M4` cost-characterization metric from `14_evaluation_scaffold.md` measures actual cache hit rates per workspace, not assumed ones.

### Verifier cost — the doubling

The hostile verifier from `13_hostile_verifier.md` runs as a **second LLM call per write run**. It uses a separate preset (`verifier` slot in `[llm.presets]`) and a separate budget (`verifier_budget_multiplier = 0.5` by default — half the writer's budget because the verifier reads-and-votes rather than plans-and-writes). Token spend per ingest is approximately **1.5× the writer's spend** (writer + 0.5× verifier).

Updated `[llm.budgets]` example:

```toml
[llm.budgets.scheduled_synthesis]
writer    = { input_tokens = 200000, output_tokens = 50000, max_usd = 2.00 }
verifier  = { input_tokens = 100000, output_tokens = 20000, max_usd = 1.00 }
total_max_usd = 3.00

[llm.budgets.batch_synthesize]
writer    = { input_tokens = 400000, output_tokens = 80000, max_usd = 4.00 }
verifier  = { input_tokens = 200000, output_tokens = 40000, max_usd = 2.00 }
total_max_usd = 6.00
```

The verifier's spend is logged separately in `~/.alexandria/logs/verifier-YYYY-MM-DD.jsonl` and `~/.alexandria/logs/llm-usage-YYYY-MM-DD.jsonl` so M4 can break out writer cost vs verifier cost. Users who consider the verifier expensive can switch its preset to a cheaper model (Sonnet rather than Opus) — its job is read+vote, which Sonnet handles competently.

## Prompt caching strategy

From `research/raw/35_anthropic_prompt_caching.md`:

- Cache read = **0.1× base input cost** — a 90% discount.
- Cache write (5m TTL) = **1.25× base input cost**.
- Cache write (1h TTL) = **2× base input cost**.
- Minimum cacheable prompt length: **4096 tokens** for Opus 4.6, 2048 for Sonnet 4.6.
- Hierarchy: `tools → system → messages`. Invalidating a level invalidates all subsequent levels.
- **Rule:** place `cache_control` on *the last block whose prefix is identical across requests*.

### How alexandria structures every Anthropic call

```python
anthropic_request = {
    "model": preset.model,
    "max_tokens": preset.max_output_tokens,
    "tools": [
        *mcp_tool_definitions[:-1],
        {**mcp_tool_definitions[-1], "cache_control": {"type": "ephemeral"}},
        # cache_control on the LAST tool → caches the entire tools array
    ],
    "system": [
        {"type": "text", "text": skill_md_content},
        {"type": "text", "text": workspace_schema_block},
        {
            "type": "text",
            "text": static_orientation_block,      # overview + index head + stable settings
            "cache_control": {"type": "ephemeral"}
            # cache_control on the LAST static system block
        },
    ],
    "messages": [
        # Dynamic content: recent log entries, pending subscriptions, current conversation.
        # NOT marked for caching — these change every call.
        {"role": "user", "content": dynamic_state_block + current_user_turn},
    ],
}
```

### What is cacheable, workspace by workspace

| Workspace size | `tools + system` total tokens | Cache hit? |
|---|---|---|
| Fresh workspace, no content yet | ~2 kTok | **No** — below Opus 4.6's 4096-token floor. Request still succeeds, just pays full price. |
| Small workspace, ~20 pages | ~6 kTok | Yes — every call after the first in a 5-min window gets 90% off the cached portion. |
| Medium workspace, ~100 pages, deep SKILL.md | ~15 kTok | Yes, significant savings on every call. |
| Large workspace | capped by what we include in `system` | Yes. We do not put the entire wiki in context — the agent reads pages on demand via `read`. The cached `system` block holds only orientation. |

The threshold matters for tiny workspaces — we document in the `alexandria cost` CLI output whether the workspace clears the minimum, and note the per-model floor. A user whose `SKILL.md + tools + orientation` is below 4096 tokens sees the same correctness, just higher per-call cost; the fix is either upgrading to Sonnet (2048-token floor) or accepting the cost until the workspace grows.

### Scheduled synthesis — the only cost-sensitive case

Scheduled synthesis is the **only** mode where alexandria's own cost matters — it is the only mode where alexandria calls the LLM. Interactive work happens in the MCP client and its cost is the client's concern, not ours. Example arithmetic:

- Workspace has 12 kTok of static orientation (SKILL.md + tool defs + overview + index head + schema).
- Weekly digest prompt has 5 kTok of dynamic content (this week's events summary).
- Scheduled ingest makes ~10 tool-use round-trips per run.

Without caching, per run on Opus 4.6:
- Input: (12k static + 5k dynamic) × 10 trips × $5/MTok = $0.85 per run
- Output: ~50k at $25/MTok = $1.25
- Total: ~$2.10 per run × 52 weeks = **~$110/year per workspace**.

With caching (12 kTok cached on the first trip, reused for 9 more within the 5m window):
- Trip 1: 12k write at $6.25/MTok + 5k input at $5/MTok = $0.10
- Trips 2–10: 12k read at $0.50/MTok + 5k input at $5/MTok = $0.031 × 9 = $0.28
- Output: ~50k at $25/MTok = $1.25
- Total: ~$1.63 per run × 52 weeks = **~$85/year per workspace**.

That is a meaningful cost reduction. For a user running scheduled synthesis on 5 workspaces, caching saves ~$125/year. More importantly, it proves the design supports unattended automation without runaway cost.

(Numbers above assume current public Claude Opus 4.6 pricing as of `raw/35_*`. The architecture adapts to whatever prices Anthropic publishes; the telemetry logs real usage per run.)

### Non-Anthropic providers

- **OpenAI** caches automatic-prefix matches for free. We do not need `cache_control` markers — we just structure the call the same way (stable prefix first, dynamic suffix last) and OpenAI caches it automatically when it can.
- **Gemini** requires creating a `CachedContent` resource separately and referencing it. Different shape but same pattern. Implementation detail for the `gemini` provider.
- **Local models** — KV cache reuse is automatic in vLLM / llama.cpp when the prefix matches. Same structural discipline pays off for free on the latency side.

## Cost control

Five mechanisms, enforced across every non-interactive run.

### 1. Per-operation token budgets

Every call to `complete()` passes a `max_output_tokens`. For scheduled and chat modes, the agent loop also enforces a **total-run budget** across all tool-use round-trips:

```toml
[llm.budgets]
# Daemon-owned operations only; budgets apply to unattended runs.
scheduled_synthesis = { max_input_tokens = 200000, max_output_tokens = 50000, max_usd = 2.00 }
scheduled_lint      = { max_input_tokens = 100000, max_output_tokens = 20000, max_usd = 1.00 }
batch_synthesize    = { max_input_tokens = 400000, max_output_tokens = 80000, max_usd = 4.00 }
batch_lint          = { max_input_tokens = 100000, max_output_tokens = 20000, max_usd = 1.00 }
```

When the budget is hit mid-run, the agent loop terminates cleanly, writes whatever it has, and logs a budget-exceeded event. Scheduled runs error out with a status so the next scheduled run isn't suppressed silently.

Interactive ingest/query/lint triggered by a user in an MCP client is **not** subject to these budgets — the client owns its own inference and enforces whatever limits it wants.

### 2. Dry-run preview

`alexandria synthesize --workspace X --dry-run` prints:
```
Would run scheduled synthesis on workspace 'customer-acme'
  Model:       claude-opus-4-6 (preset: claude-opus)
  Input est:   ~17000 tokens  (12k cached, 5k fresh)
  Output cap:  50000 tokens
  Cost est:    $0.10 (cache write) + $1.25 (output) = ~$1.35
  Duration est: ~45 seconds
Proceed? [y/N]
```

Same for `alexandria ingest --dry-run` and `alexandria lint --dry-run`. Reuses the provider's `estimate_cost()`.

### 3. Monthly caps per workspace

Optional, off by default:
```toml
[workspace.customer-acme.llm.caps]
monthly_usd = 20.00       # hard cap
warn_at     = 15.00       # warn in status + logs
```

When hit, scheduled runs are disabled until the start of the next calendar month or until the user runs `alexandria llm caps reset --workspace customer-acme`.

### 4. Telemetry

Every completion call logs to `~/.alexandria/logs/llm-usage.jsonl`:
```json
{"ts":"2026-04-15T09:00:00Z","workspace":"customer-acme","op":"scheduled_synthesis",
 "preset":"claude-sonnet","model":"claude-sonnet-4-6",
 "input_tokens":17000,"cache_read_tokens":12000,"cache_write_tokens":0,
 "output_tokens":42000,"usd_estimate":1.08,"latency_ms":42000,
 "stop_reason":"end_turn","tool_calls":12}
```

`alexandria llm cost [--workspace X] [--since 30d]` rolls this up for display. No cloud, no telemetry exports — strictly local.

### 5. Opt-in for scheduled runs

As already specified in `10_event_streams.md`: scheduled synthesis is **disabled by default** per workspace. Users opt in explicitly with `alexandria synthesize enable --workspace X`. The first enablement prompts for budget caps and cost preset. This is the single biggest safety valve — the user cannot be surprised by scheduled cost.

## API key storage

Same pattern as source-adapter credentials (`06_data_model.md`):

- Keys live in `~/.alexandria/secrets/<ref>.enc`.
- Encryption key derived from the OS keyring (`keyring` library — macOS Keychain, Linux Secret Service / libsecret, Windows Credential Locker). Passphrase fallback for headless environments.
- `config.toml` references by name (`api_key_ref = "anthropic_key"`), never by value.
- `alexandria auth set anthropic --key sk-ant-...` or `alexandria auth set anthropic --interactive` stores the key; `alexandria auth list` shows names + masked prefixes; `alexandria auth remove anthropic` clears it.
- **Keys are never returned through MCP.** The `sources` / `events` / `subscriptions` MCP tools can list adapter *names* but not tokens. This is invariant 10 in `01_vision_and_principles.md` applied to LLM credentials.

## Rate limits, retries, and fallback

Every provider exposes its rate limits through error responses. The wrapper handles:

- **429 / 529** (rate-limited, overloaded) — exponential backoff with jitter. Up to 5 retries, cap at 30 seconds between attempts.
- **500 / 502 / 503** (server errors) — retry with backoff, up to 3 attempts.
- **400 / 401 / 403 / 413** (client errors) — no retry; fail fast and log the full error to `~/.alexandria/logs/llm-errors.jsonl`.
- **Timeout (default 120s)** — configurable per preset.

### Fallback chains (optional)

Users can configure a fallback chain per operation:

```toml
[llm.routing]
scheduled_synthesis = ["claude-sonnet", "gpt-o", "local-llama"]
```

If the primary preset fails with a rate-limit or server error after retries, the wrapper tries the next preset in the chain. Rationale: scheduled synthesis must be robust against transient provider outages; the user can name a local model as the ultimate fallback so the run completes even when all cloud providers are down.

Interactive chat does not auto-fall-back without prompting — if the primary fails, the CLI prompts the user to retry or switch.

## Local and self-hosted inference — setup recipes

Local inference matters for three reasons: **privacy** (content never leaves the machine or network), **offline use**, and **cost reduction** for high-volume automation. All supported via the `openai-compatible` provider. Four concrete setup recipes for the stacks users most commonly run:

### Recipe 1 — Ollama (laptop, easiest)

```bash
ollama pull llama3.3:70b                          # or qwen2.5:72b, mistral-large, etc.
alexandria llm add local-ollama \
  --provider openai-compatible \
  --endpoint http://localhost:11434/v1 \
  --model llama3.3:70b
alexandria llm test local-ollama
alexandria llm route scheduled_synthesis local-ollama
```

### Recipe 2 — vLLM (GPU box, production throughput)

```bash
# On the GPU machine
pip install vllm
vllm serve Qwen/Qwen2.5-72B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 \
  --enable-prefix-caching          # critical: enables prefix KV reuse

# On the client
alexandria llm add gpu-qwen \
  --provider openai-compatible \
  --endpoint http://gpu-box.local:8000/v1 \
  --model Qwen/Qwen2.5-72B-Instruct
alexandria llm test gpu-qwen
```

Prefix caching in vLLM is conceptually identical to Anthropic's prompt caching — the stable `tools + system` prefix is kept in the KV cache, and every subsequent call with the same prefix skips the re-computation. Our structural discipline (stable first, dynamic last) gives the same latency win without any per-message cache markers.

### Recipe 3 — SGLang (GPU box, fastest for structured output)

```bash
pip install "sglang[all]"
python -m sglang.launch_server \
  --model-path meta-llama/Llama-3.3-70B-Instruct \
  --host 0.0.0.0 --port 30000

alexandria llm add gpu-llama \
  --provider openai-compatible \
  --endpoint http://gpu-box.local:30000/v1 \
  --model meta-llama/Llama-3.3-70B-Instruct
```

SGLang's **RadixAttention** gives tree-structured prefix sharing — multiple agent sessions against the same workspace share the cached `system` block automatically. Particularly valuable for heavy scheduled synthesis workloads.

### Recipe 4 — LiteLLM proxy (access 100+ providers as one endpoint)

```yaml
# ~/litellm-config.yaml
model_list:
  - model_name: claude-opus
    litellm_params:
      model: anthropic/claude-opus-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: gpt-5
    litellm_params:
      model: openai/gpt-5
      api_key: os.environ/OPENAI_API_KEY
  - model_name: together-llama
    litellm_params:
      model: together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo
      api_key: os.environ/TOGETHER_API_KEY
```
```bash
litellm --config ~/litellm-config.yaml --port 4000
alexandria llm add gateway \
  --provider openai-compatible \
  --endpoint http://localhost:4000/v1 \
  --model claude-opus           # or gpt-5, together-llama, etc.
```

One alexandria preset, any underlying provider. Useful when the user wants to switch providers without reconfiguring alexandria.

### What works well locally vs where frontier models still win

- **Scheduled synthesis and lint** — structured tasks, Llama 3.3 70B / Qwen 2.5 72B / DeepSeek V3 all perform acceptably. Tool use is reliable. These are the exact workloads alexandria's daemon drives, so local models are a first-class option for the scheduled-daemon mode.
- **Complex batch synthesis with cascade updates** (`alexandria synthesize` on a large workspace with many cross-references) — frontier models (Claude Opus 4.6, GPT-5) still win on quality. Local is possible but the user should expect more review work and set appropriate budgets.
- **Tool-use reliability on sub-30B models** — inconsistent. The wrapper probes capability via `alexandria llm test <preset>` and falls back to JSON-parsing emulation when native tool calling is unavailable.

Interactive work is not alexandria's concern — that happens in the MCP client, which brings its own model choice. A user who wants "local-only everywhere" runs Claude Code or similar pointed at an Ollama / vLLM endpoint themselves (Claude Code and other MCP clients support this independently) and configures alexandria's scheduled daemon to match.

We do not ship model weights. The user is responsible for their serving stack. alexandria's job is to speak the OpenAI-compatible protocol correctly against whatever endpoint is running — and in practice that covers the entire open-weight ecosystem plus every closed-source provider via LiteLLM.

## What alexandria explicitly does not do

**No interactive chat client.** There is no `alexandria chat` REPL. No terminal UI hosting a conversation. No streaming output rendered by alexandria to a user. No chat history stored per-session on our side. No `/history` / `/clear` / `/save` commands. Interactive work happens in Claude Code, Cursor, Claude.ai, Codex, Claude Desktop, or any other MCP-capable agent — those tools already do it well, and alexandria does not compete with them.

The load-bearing reason: **alexandria is the knowledge engine, not the agent runtime**. Building a chat client would duplicate what every MCP agent already provides, while pulling alexandria's design focus away from the things only alexandria can do — maintaining the workspace, running event streams, compiling wikis, validating citations, and serving the tool surface that makes all of this accessible to any agent.

The daemon-owned agent loop for scheduled synthesis is structurally a tiny runner — tens of lines of Python wrapping the provider's tool-use cycle (`complete → receive tool_use → execute tool → feed tool_result → repeat until end_turn or budget`). It has no user interaction because there is no user in the room. It writes results to disk, logs cost, and exits. That is a fundamentally different thing from a chat client and does not grow into one.

## Closing open question 07.A

`07_open_questions.md` Section A asked *"where does the agent loop actually run?"*. This doc decides the answer:

- **Client MCP is the only interactive mode** and handles all user-facing work. alexandria has no inference configuration for it.
- **Daemon-owned operations** are the only place alexandria itself calls an LLM. Scheduled synthesis, scheduled lint, and CLI batch runs (`alexandria synthesize`, `alexandria lint --run`). All opt-in, budgeted, dry-run previewable, with mandatory cost telemetry.
- **`alexandria chat` is explicitly not built.** Users who want interactive chat use an MCP client.

Both modes share the same tool surface (`04_guardian_agent.md`), the same workspace boundaries, the same data model, and the same agent-loop shape. The difference is who holds the loop.

## Open questions

1. **Model classification for routing.** Today routing is static (`chat → claude-opus`). A smarter version would classify each query and route cheap queries to Sonnet, complex ones to Opus. We decline this at MVP for the same reasons we declined adaptive RAG: the *agent* should adapt its own effort, not an external router. If users report consistent over-use of Opus for trivial queries, we revisit.

2. **Caching SKILL.md across workspaces.** Every workspace has its own SKILL.md but they share a common template. A future optimization: structure the system block as `[common template] + [workspace-specific delta]` with the cache_control on the common part, so a user with many workspaces gets cache hits across workspaces in the same 5-minute window. Non-trivial because current Anthropic caching is per-API-key request prefix; worth revisiting if caching semantics change.

3. **Streaming tool-use parsing.** The cleanest chat UX streams tool calls as they are generated. The Anthropic SDK supports this via the streaming API, but our wrapper has to parse partial tool_use blocks correctly. Not a blocker — we buffer to the end of each block if the SDK returns incomplete deltas, at the cost of slightly less interactive feel.

4. **Multi-agent orchestration run by alexandria.** Mode 2 and 3 could support spawning subagents inside alexandria (using the same `AnthropicProvider` as the lead) for cross-workspace synthesis or heavy research tasks. Architecture is ready for it (re-entrant MCP server, external memory via `wiki_log_entries`). Not MVP.

5. **On-device fine-tuning.** Karpathy's original tweet mentions *"synthetic data generation + finetuning to have your LLM know the data in its weights."* Explicitly deferred. The pattern needs years more research before it's a stable personal-tool feature.
