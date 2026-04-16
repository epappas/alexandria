# Review: LLM Architect

**Reviewer:** llm-architect specialist agent
**Date:** 2026-04-16
**Scope:** Full architecture + research folder, with focus on LLM application architecture, tool-surface coherence, prompt caching, and the agentic retrieval charter.

**Note on line references:** The reviewer could not consistently cite exact line numbers (the agent had read-only access without a line-aware viewer). Where a line is cited, treat it as approximate.

---

## 1. Executive take

The architecture is intellectually honest about what it is and isn't, which is rare. The agentic-retrieval charter (`docs/research/reference/12_agentic_retrieval.md`, `13_agentic_retrieval_design_space.md`) is well-argued for the stated target: a **single-user, local, retroactive-query knowledge engine** whose consumer is a Claude-class agent with long context and bounded tool-call latency. The rejection of vector stores is not contrarianism — it follows from invariant #13's cost/benefit accounting. The scheduled-daemon agent loop in `11_inference_endpoint.md` correctly separates the *interactive* loop (owned by Claude Code) from the *unattended* loop (owned by alexandria), and this split is the most important architectural decision in the repo. Most of the doc set holds up under scrutiny.

The biggest concern is not in the retrieval charter — it's in the **agent-ergonomics of the tool surface when consumed from a connected MCP client**. `04_guardian_agent.md` and `08_mcp_integration.md` describe ~11–14 primitives, but the documentation underweights (a) how many turns a naïve Claude Code session will burn to traverse them, (b) the lack of a canonical "cheap cold-start" tool that returns a workspace silhouette in one call, and (c) the fact that the "agent-as-retriever" thesis is load-bearing on the *caller* agent being long-context and disciplined — which Claude Code is, but Cursor's agent mode and Codex are less so. This is a capability-dependency we've glossed. Second concern: the L0/L1 tiered wake-up budgets in `04_guardian_agent.md` collide with Anthropic's prompt-caching floors (Opus: 4096 tokens, Sonnet: 2048 tokens) in a way that makes L0's nominal "500 token" budget effectively meaningless for caching purposes on Opus. That needs to be said out loud in the doc.

## 2. Specific Critiques

### 2.1 The agentic-retrieval charter is sound but has two named failure modes that aren't in the docs

`docs/research/reference/12_agentic_retrieval.md` builds the case on (a) Anthropic's multi-agent research post, (b) Karpathy's tweet, (c) the epappas gist synthesizing arxiv work. The case is correct for the stated target. But two failure modes aren't named:

1. **The "100K files of 200 tokens each" regime.** SQLite FTS5 `grep`/`search` latency is fine up to ~1M rows; beyond that, query latency degrades and agents will start timing out or burning turns. `12_agentic_retrieval.md` should state the regime where FTS5-only retrieval is defensible (I'd put it at ≤500K wiki pages + ≤5M events). Beyond that, the agent-as-retriever thesis doesn't automatically break, but the primitives need to change (sharding, per-directory FTS indexes, or a hierarchical `overview` tool that pre-aggregates). This is not in `13_agentic_retrieval_design_space.md`'s Tier-1 indexing column, and it should be.

2. **The "model can't plan retrieval" regime.** The thesis assumes the caller is GPT-5-class or Claude-4-class. If a user points an older or weaker model at alexandria via MCP, the agent-as-retriever pattern will produce worse results than a vector store would. `12_agentic_retrieval.md` frames this as purely a target-user choice, but it's actually a *runtime capability check* the guardian could do (inspect the caller's advertised model in MCP metadata). This is worth naming.

### 2.2 Tool surface has one missing primitive: `overview` / `silhouette`

`docs/architecture/04_guardian_agent.md` and `08_mcp_integration.md` list `guide`, `list`, `grep`, `search`, `read`, `follow`, `history`, `write`, `delete`, `sources`, `subscriptions`, plus events/timeline/git_* when active adapters exist. This is composable, and most of the set is non-redundant.

**The missing primitive is a cheap cold-start silhouette tool.** When Claude Code first binds to an alexandria workspace, its first instinct will be to call `guide` (good, gives policy) and then `list` recursively (bad, expensive, and the agent doesn't know depth budgets). Every connected session will burn 3–8 turns rediscovering the shape of the workspace. A single `overview` / `silhouette` tool that returns:
- top-level directory tree (depth 2)
- recent wiki-page titles (last 20)
- recent event counts by source (last 7 days)
- count of pinned pages
- token estimate of each

... in one call, would collapse the cold-start cost. This is analogous to `ls -la` + `git status` + `git log --oneline -20` combined. The absence of this is the single biggest friction a real Claude Code session will hit. It should be in `04_guardian_agent.md`'s tool table, not handled by telling the agent to compose `list` + `events` + `history`.

### 2.3 `guide` tool is both under-specified and doing too much

`04_guardian_agent.md` describes `guide` as returning "operating policy, tool usage conventions, and workspace invariants". This is correct in spirit but collides with prompt caching. If `guide` content changes across calls (e.g. because it dynamically injects the current pinned-page list), it breaks cache prefix stability. If it doesn't change, it should just be part of the system prompt that the MCP client injects once per session — which is what most clients will do anyway.

The doc should either (a) commit to `guide` being a stable-across-calls string that changes only on workspace config change, and be treated as a system-prompt candidate for callers that support it; or (b) acknowledge it's a dynamic tool and explicitly not cacheable, with the cost implications spelled out. Right now it's ambiguous.

### 2.4 L0/L1 tiered wake-up budgets collide with Anthropic caching floors

`04_guardian_agent.md` describes L0 at 500 tokens and L1 at 1500 tokens. `docs/research/raw/35_anthropic_prompt_caching.md` (which the design correctly cites) states Anthropic's minimum cacheable block is **4096 tokens on Opus 4.x** and **2048 tokens on Sonnet 4.x**.

This means: the nominal L0 500-token budget **cannot produce a cacheable prefix by itself on Opus**. If the daemon is running Opus 4.6, L0 is effectively uncached on first call and only becomes cacheable once the `tools + system + messages` prefix *together* crosses 4096. In practice the tools block alone will be larger than 4096 tokens for an 11-tool surface with JSON schemas, so the prefix naturally clears the floor — but this needs to be said explicitly in `11_inference_endpoint.md`. Right now the doc implies "500-token L0 is cheaper because of caching" and that's only true *after* you've paid to warm the cache once per tool-surface version.

The L1 1500-token budget is fine on Sonnet (2048 floor) if the tools+system prefix is already ≥548 tokens, which it will be.

**The split is not theatre — it's load-bearing because L0 is for "is there anything interesting in this event batch?" gating, and L1 is for actual synthesis — but the budget numbers need to be rewritten as *output* budgets, not *total call* budgets.** I suspect that's what was meant, but it isn't what the doc says. This is a 10-minute fix that prevents a real footgun.

### 2.5 Prompt caching strategy is correct in shape, imprecise in arithmetic

`11_inference_endpoint.md`'s structure — stable `tools → system → messages` prefix with cache breakpoints — matches Anthropic's guidance in `raw/35_*`. Two issues:

1. **Cache TTL.** Anthropic's default is 5 minutes, with an extended 1-hour option at 2x write cost. The scheduled-daemon use case (weekly synthesis) will miss cache almost every time because runs are hours apart. The doc should either (a) explicitly acknowledge the daemon is *not* the caching beneficiary and caching is only for interactive-agent-through-MCP paths, or (b) commit to the 1-hour cache + accept the 2x write cost for back-to-back synthesis batches that run within an hour. Right now the doc conflates the two paths.

2. **Cost arithmetic.** The doc estimates cache-hit savings as 90% (standard Anthropic marketing number). That's correct for the *hit* rows. But the effective savings depend on hit rate, which for a weekly daemon is ~0%. The honest number for the daemon path is "prompt caching saves nothing; we still structure prefixes as-if for caching because the interactive path through MCP benefits." Say that.

### 2.6 Scheduled synthesis agent loop has one unnamed failure mode: partial write on crash

`11_inference_endpoint.md` describes a bounded-budget daemon with dry-run preview and draft-until-confirmed writes. The shape is correct — bounded turns, bounded tokens, explicit stop conditions. The failure mode that isn't named: **what happens if the daemon crashes mid-synthesis after writing 3 of 7 draft pages?**

The current doc implies draft pages are marked as drafts until a confirm step promotes them. Good. But it doesn't say what happens to the *partial* state: does the next daemon run resume, re-do, or abandon? SQLite event log can record "synthesis run started" / "synthesis run committed", but if the filesystem has 3 orphan draft markdown files and SQLite has no commit record, the invariants diverge. `10_event_streams.md` is right that SQLite is authoritative for events and FS is authoritative for documents, but the *synthesis-run envelope* is a cross-store transaction that isn't covered.

Fix: define a synthesis run as `{run_id, started_at, status}` row in SQLite, with draft files named `.alexandria/drafts/{run_id}/*.md`. On startup, the daemon scans for orphan draft dirs with no committed run_id and either resumes or deletes them based on age. This needs one paragraph in `11_inference_endpoint.md`.

### 2.7 Workspace binding modes (open vs pinned) in `08_mcp_integration.md`

The open/pinned distinction is the right axis. One critique: the doc doesn't say what happens when a pinned workspace is bound by *two* MCP clients simultaneously (Claude Code + Claude Desktop, say). Since alexandria is single-user, concurrent reads are fine; concurrent writes need SQLite's WAL mode (presumably already assumed) and a single-writer lock on the filesystem side for the document store. This should be stated explicitly, even if the answer is "first writer wins, second gets an error and retries".

### 2.8 The mempalace comparison in `14_mempalace.md` is mostly honest but soft in one place

The framing — "different targets, not wrong" — is intellectually honest. The place it gets soft is where it implies mempalace's vector bet is "also valid for their target" without specifying *what target*. Mempalace is (I gather) building for multi-user, cross-session semantic recall at conversational latencies with fuzzy queries. That's a real target where vectors win. alexandria's target is single-user, retroactive, exact-identifier-heavy queries ("what did I decide about the auth refactor in March?") where FTS5 + agent navigation wins. Say that explicitly in `14_mempalace.md` — the comparison is more credible when both targets are named, and right now it reads like diplomacy.

## 3. Missing Pieces (ranked by importance)

1. **`overview` / `silhouette` tool.** Single biggest ergonomic gap for connected agents. Add it.
2. **Synthesis-run transactional envelope.** Crash recovery story for partial daemon runs is absent. Add one paragraph to `11_inference_endpoint.md`.
3. **Explicit regime statement for FTS5 retrieval.** Name the file-count / row-count regime where the agent-as-retriever thesis holds. Add to `12_agentic_retrieval.md`.
4. **Caller model capability acknowledgment.** The thesis depends on the caller being a long-context, tool-disciplined model. Name the dependency in `12_agentic_retrieval.md` or `08_mcp_integration.md`.
5. **Daemon cache-TTL honesty.** Clarify that the weekly daemon path does not benefit from prompt caching; caching is for the interactive-MCP path. Add to `11_inference_endpoint.md`.
6. **L0/L1 budgets as output budgets, not total-call budgets.** One-line rewrite in `04_guardian_agent.md`.
7. **Concurrent-writer story.** What happens when two MCP clients bind the same workspace? One paragraph in `08_mcp_integration.md`.
8. **Mempalace comparison sharpening.** State both targets. `14_mempalace.md`.

## 4. Recommendations

1. **Add an `overview` tool** to the guardian surface. Returns a structured silhouette (tree depth 2 + recent titles + recent event counts + pinned pages + token estimates) in one MCP call. This is the single highest-leverage change in the review. Put it in `04_guardian_agent.md`'s tool table and reference it from `08_mcp_integration.md`.

2. **Rewrite L0/L1 budget numbers in `04_guardian_agent.md`** as `max_output_tokens` explicitly, not "call budgets", and add a sentence acknowledging the prefix (tools + system) is already larger than the Anthropic caching floor because of the tool-schema block. This closes the footgun.

3. **Add a "synthesis run envelope" section to `11_inference_endpoint.md`** defining `{run_id, started_at, status}` in SQLite + `.alexandria/drafts/{run_id}/*.md` on disk, with a daemon-startup recovery scan. Three paragraphs max.

4. **Add a "retrieval regime" callout to `12_agentic_retrieval.md`** stating the wiki-page and event-row counts beyond which the FTS5-only approach needs sharding or hierarchical overviews. Frame it as "where the thesis holds" not "where it breaks".

5. **In `11_inference_endpoint.md`**, split the caching section into two subsections: "Interactive path through MCP (cache-benefiting)" and "Unattended daemon path (cache-neutral but prefix-structured for consistency)". This removes the conflation.

6. **Add a one-paragraph "caller capability assumptions" note** in `08_mcp_integration.md` stating that the agent-as-retriever thesis assumes a caller with ≥128K context and reliable tool-use discipline, and naming which MCP clients are known to meet this bar (Claude Code, Claude Desktop, Cursor agent mode in practice) and which don't (older GPTs, smaller local models via MCP bridges).

7. **Sharpen `14_mempalace.md`** by naming both targets in one sentence each. The comparison becomes more credible, not less.

8. **Leave the core charter alone.** The invariants in `01_vision_and_principles.md` are sound. The agent-as-retriever bet is well-grounded. The three-layer / three-op model is clean. The workspace-per-project / SQLite-alongside-FS decision is correct. Do not re-open these.

The architecture is in better shape than most I review at this stage. The critiques above are all surface-level refinements to a sound core; none require re-litigating a prior decision. The highest-value item on the list is the `overview` tool — everything else is cleanup.
