# Source: Anthropic — Prompt Caching docs

- **URL:** https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching (previously `docs.anthropic.com/en/docs/build-with-claude/prompt-caching`)
- **Fetched:** 2026-04-15
- **Purpose:** load-bearing facts for `architecture/11_inference_endpoint.md` — what can be cached, the cost discount, TTLs, minimum sizes, and invalidation rules.

---

## Mechanism (verbatim)

> "When you send a request with prompt caching enabled:
> 1. The system checks if a prompt prefix, up to a specified cache breakpoint, is already cached from a recent query.
> 2. If found, it uses the cached version, reducing processing time and costs.
> 3. Otherwise, it processes the full prompt and caches the prefix once the response begins."

## What can be cached (verbatim)

> "Most blocks in the request can be cached. This includes:
> - **Tools**: Tool definitions in the `tools` array
> - **System messages**: Content blocks in the `system` array
> - **Text messages**: Content blocks in the `messages.content` array, for both user and assistant turns
> - **Images & Documents**: Content blocks in the `messages.content` array, in user turns
> - **Tool use and tool results**: Content blocks in the `messages.content` array, in both user and assistant turns"

## Pricing (verbatim)

> "- 5-minute cache write tokens are **1.25 times** the base input tokens price
> - 1-hour cache write tokens are **2 times** the base input tokens price
> - **Cache read tokens are 0.1 times** the base input tokens price"

**Example (Claude Opus 4.6):**
| Operation | Price per MTok |
|---|---|
| Base input | $5 |
| 5m cache write | $6.25 (1.25×) |
| Cache hit/read | **$0.50 (0.1×)** |
| Output | $25 |

**Key fact:** cache reads are **90% cheaper** than base input tokens.

## TTL

- **Default 5 minutes**, refreshed on every hit.
- **Extended 1-hour** TTL available via `cache_control: {"type": "ephemeral", "ttl": "1h"}` at higher write cost.
- > "The 1-hour cache is best used in the following scenarios: When you have prompts that are likely used less frequently than 5 minutes, but more frequently than every hour... When latency is important and your follow up prompts may be sent beyond 5 minutes."

## Minimum cacheable prompt length

> "The minimum cacheable prompt length is:
> - **4096 tokens** for Claude Mythos Preview, Claude Opus 4.6, and Claude Opus 4.5
> - **2048 tokens** for Claude Sonnet 4.6
> - **1024 tokens** for Claude Sonnet 4.5, Claude Opus 4.1, Claude Opus 4, Claude Sonnet 4, and Claude Sonnet 3.7
> - **4096 tokens** for Claude Haiku 4.5
> - **2048 tokens** for Claude Haiku 3.5 and Claude Haiku 3"

> "Shorter prompts cannot be cached, even if marked with `cache_control`. Any requests to cache fewer than this number of tokens will be processed without caching, and **no error is returned**."

## Invalidation hierarchy (verbatim)

> "Modifications to cached content can invalidate some or all of the cache. The cache follows the hierarchy: `tools` → `system` → `messages`. Changes at each level invalidate that level and all subsequent levels."

| Change | Tools | System | Messages | Impact |
|---|---|---|---|---|
| Tool definitions | ✘ | ✘ | ✘ | Entire cache invalidated |
| System prompt text | ✓ | ✘ | ✘ | System + messages invalidated |
| Images added/removed | ✓ | ✓ | ✘ | Messages only |

## The key rule (verbatim)

> "Place `cache_control` on the **last block whose prefix is identical across requests**."

Anti-pattern: putting `cache_control` on a block that includes a timestamp or per-request data. The prefix hash changes every call, cache never hits.

## Token accounting (verbatim)

```python
response.usage.cache_creation_input_tokens   # Tokens written to cache
response.usage.cache_read_input_tokens       # Tokens read from cache
response.usage.input_tokens                  # Tokens AFTER last breakpoint
```

Total input cost = `cache_read * 0.1×` + `cache_creation * 1.25×` + `input_tokens * 1.0×`.

## Implication for alexandria

The alexandria guardian calls Claude in a shape that is ideal for this mechanism:

1. **`tools`** — the nine MCP tool definitions. Stable across every call in a session. **Cache at the end of the `tools` array.**
2. **`system`** — the SKILL.md content, the workspace's schema, the static orientation block. Stable across every call for the same workspace. **Cache at the end of the `system` array.**
3. **`messages`** — dynamic. The current conversation plus the current `guide()` output (which changes per session because it includes recent log entries). **Do not cache the dynamic block.**

At our target workspace size, the SKILL.md + tool definitions + overview easily clears 4096 tokens (the Opus 4.6 minimum). A workspace with < 4096 tokens of static content falls back to no caching — the call still works, it just costs more. We document this threshold so users with tiny workspaces understand why their per-call cost is higher.

**Estimated savings for scheduled synthesis** (main cost concern): weekly digest runs against a workspace with ~10 kTok of cached orientation + ~5 kTok of variable event data. Without caching: ~$75/million output tokens equivalent on Opus 4.6. With caching: the 10 kTok static block costs 10 × $0.50 = $5/MTok instead of 10 × $5 = $50/MTok on every call. About **90% reduction on the input side** of every scheduled run after the first warm-up call.
