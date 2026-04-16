# Reference: Agentic Retrieval — the agent is the retriever

**Sources:** `raw/22_anthropic_building_effective_agents.md`, `raw/23_anthropic_multi_agent_research.md`, `raw/24_anthropic_claude_code_best_practices.md`, `raw/25_anthropic_contextual_retrieval.md`, and `raw/00_karpathy_tweet.md`.

**See also:** `13_agentic_retrieval_design_space.md` — maps the 2025–2026 retrieval-archetype landscape (Tier 1 indexing × Tier 2 execution), including HippoRAG 2, CatRAG, RAPTOR, and the multi-agent engineering lessons we adopt.

## The case for rejecting RAG as alexandria's retrieval model

Two quotes carry the weight of this decision.

**Karpathy, on his own research wiki (`raw/00_*`):**

> "I thought I had to reach for fancy RAG, but the LLM has been pretty good about auto-maintaining index files and brief summaries of all the documents and it reads all the important related data fairly easily at this ~small scale."

**Anthropic, on their multi-agent research system (`raw/23_*`):**

> "Traditional approaches using Retrieval Augmented Generation (RAG) use static retrieval ... our architecture uses a multi-step search that dynamically finds relevant information, adapts to new findings, and analyzes results to formulate high-quality answers."

Both agree on the same pivot: **static retrieval is the wrong organizing principle.** What replaces it is *dynamic multi-step search driven by the agent itself*. The agent generates its own queries, picks its own tools, decides what to read, iterates, and stops when it has the answer.

## Anthropic's own definition of an agent

From *Building Effective Agents* (`raw/22_*`, verbatim):

> "Agents: systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks."

> "[Agents are] typically just LLMs using tools based on environmental feedback in a loop."

The word *dynamically* is doing work. An agent does not consume a pre-built retrieval pipeline — it **is** the retrieval pipeline. Our job is to give it good tools and get out of the way.

## The fundamental constraint: context, not recall

From *Claude Code Best Practices* (`raw/24_*`, verbatim):

> "Most best practices are based on one constraint: Claude's context window fills up fast, and performance degrades as it fills."

> "Let Claude fetch what it needs. Tell Claude to pull context itself using Bash commands, MCP tools, or by reading files."

RAG's failure mode at personal scale is not "the embedding missed the right chunk." It is "the top-10 retrieved chunks all looked relevant, so we stuffed them into context, and now the agent is drowning in noise it didn't ask for." The model's ability to reason is bounded by context quality, and context quality is maximized when the agent chose every token in it.

This is the opposite of the RAG bet. RAG assumes more retrieved chunks = better answer. Agentic retrieval assumes fewer, better-chosen reads = better answer.

## The retrieval primitives Claude Code uses

Claude Code has no vector store. It has:

- **Read** — fetch file contents (or ranges).
- **Glob** — list files by pattern.
- **Grep** — regex search across files.
- **Bash** — arbitrary shell for anything else.
- **CLAUDE.md** — an orientation document the agent reads every session.
- **Subagents** — spawn a child agent with its own context window for wide exploration; return a summary.

These five primitives plus a single orientation file are enough to navigate codebases of arbitrary size. Anthropic has published this as the official best practice. Our architecture needs the same trio: **primitives + orientation doc + subagents**.

## The Claude Code playbook, literally renamed for alexandria

| Claude Code | alexandria |
|---|---|
| Codebase | Workspace |
| `CLAUDE.md` | `SKILL.md` (per workspace) |
| `Read` | `read(workspace, path, pages?, sections?)` |
| `Glob` | `list(workspace, path, glob)` |
| `Grep` | `grep(workspace, pattern, path?)` — regex / exact match |
| `Bash` — ad-hoc | not exposed (scope: knowledge, not execution) |
| Subagents | spawned by the calling MCP client; we design tools to be safely re-entrant |
| Plan Mode (explore → plan → code) | explore (guide + list + read index) → plan → synthesize |

## The five-primitive tool surface alexandria must expose

1. **`guide(workspace)`** — orientation. Reads `SKILL.md`, `overview.md`, `index.md`, tail of `log.md`. Called first, every session. **This is the agent's CLAUDE.md.**
2. **`list(workspace, path, glob?)`** — structural navigation. Like `ls` or Claude Code's Glob.
3. **`grep(workspace, pattern, path?)`** — regex / exact-match pattern search. The sharp tool for symbol names, error codes, direct quotes.
4. **`search(workspace, query, path?)`** — FTS5 keyword search with ranking. The broad tool for "pages about concept X." Not a retriever — a primitive.
5. **`read(workspace, path, pages?, sections?)`** — fetch content. Single or glob-batch. The agent decides what to read.

Plus two alexandria-specific primitives that encode provenance:

6. **`follow(workspace, from_page, footnote_id)`** — jump from a wiki page's footnote to the cited raw source. Uses `wiki_claim_provenance` under the hood.
7. **`history(workspace, op?, since?)`** — structured query over `wiki_log_entries`. The self-awareness primitive.

Plus the two write primitives (unchanged):

8. **`write(workspace, command, path, ...)`**
9. **`delete(workspace, path)`**

## Where this thesis holds — explicit regime statement

The agent-as-retriever bet is correct **for a specific operating regime**, and the docs should say where:

- **Wiki pages per workspace:** ≤ 5,000 pages. Beyond ~5,000, FTS5 latency and agent context-budget pressure both grow non-linearly, and the agent starts burning turns.
- **Event rows per workspace:** ≤ 5,000,000 events. SQLite FTS5 over `events_fts` handles this comfortably; beyond that, the indexes start to need partitioning.
- **Concurrent active sessions:** ≤ 10 MCP clients on the same workspace. Beyond that, the per-workspace file lock from `architecture/08_mcp_integration.md`'s "Concurrent writers" section becomes a contention bottleneck.
- **Caller model class:** ≥ 128K context window, reliable tool-use discipline. Frontier models (Claude Opus 4.x, Claude Sonnet 4.x, GPT-5) consistently meet this. Sub-30B local models often do not. The capability floor test in `architecture/14_evaluation_scaffold.md` measures this per-preset.

**Beyond these regimes**, the thesis does not automatically break — but the primitives need to evolve. Sharded FTS, hierarchical overview indexes, capability-aware tool routing, multi-workspace synthesis. None of these require giving up the agent-as-retriever stance; they extend it.

## Caller capability is a runtime dependency, not just a target-user choice

The agent-as-retriever bet assumes the **caller** running the agent loop is a frontier model. If a user points a weaker model at alexandria via MCP, the pattern produces measurably worse results than a vector store would on the same workspace. This is not a flaw in the architecture — it is a **runtime capability dependency** that the user must satisfy.

`architecture/14_evaluation_scaffold.md`'s capability floor test (`alexandria eval floor --preset <preset>`) measures this. Users running below the floor see a warning at daemon startup. The architecture does not stop working below the floor; it degrades silently, which the warning makes visible.

## Why this is not "we just forgot to build a vector store"

A vector store is *extra infrastructure* that exists to paper over the fact that the model cannot browse. The model **can** browse. At the scale alexandria targets — workspaces of tens to a few thousand pages — the agent can reach every relevant page through navigation primitives in a bounded number of tool calls, and the reads it does make are the reads it chose.

If a workspace grows past that point, the fix is not pgvector. The fix is:
1. Better orientation docs (summaries at multiple levels).
2. Better subagent patterns (one subagent per topic, return summaries).
3. The lint pass producing topic-level overview pages the agent can read instead of scanning every concept.

These are all *agent-native* fixes — they scale by making the agent's navigation smarter, not by adding a parallel retrieval system that drops off responsibility for context management.

## What this means for alexandria specifically

1. **Drop pgvector entirely.** It was a hedge; it is an anti-pattern. FTS5 + glob + grep + read are sufficient at our target scale.
2. **`search` is not "the retriever."** It is one primitive among several. The agent's reasoning loop is the retriever. Documentation and system prompt must reflect this.
3. **Add `grep` as a first-class tool.** FTS5 is wrong for exact quotes, error codes, symbol names, and phrases with punctuation. `grep` (ripgrep under the hood) is the right primitive for those.
4. **Add `follow` as a first-class tool.** Following citations from a wiki page to its raw source is a dedicated operation, not just another `read`. It encodes the graph-walk semantics that make our wiki worth building.
5. **Subagent re-entrancy is a design requirement.** The MCP server must handle concurrent calls cleanly so that a client (Claude Code, Claude.ai) can spawn multiple subagents that all hit alexandria at once.
6. **The `guide()` tool is load-bearing and must stay small.** Claude Code's warning about bloated CLAUDE.md applies to our SKILL.md. If it grows unbounded, the agent stops reading it. Ruthless pruning is a design rule.
7. **Reframe the architecture's RAG-adjacent language.** Our reference doc `09_graph_rag_literature.md` calls alexandria "personal-scale Graph RAG." That concedes too much. The correct framing is **agentic search over a compiled wiki**, with the Graph RAG literature as a contrasting approach for larger scales.
