# Reference: The Agentic Retrieval Design Space (epappas gist + four arxiv papers)

**Sources:**
- `raw/26_epappas_agentic_retrieval_archetypes.md` — the user's own compiled reference map of 2025–2026 retrieval paradigms.
- `raw/27_singh_agentic_rag_survey.md` — Singh et al., *Agentic Retrieval-Augmented Generation: A Survey* (arxiv 2501.09136).
- `raw/28_hipporag2.md` — Gutiérrez et al., *HippoRAG 2 / From RAG to Memory* (arxiv 2502.14802).
- `raw/29_liang_reasoning_agentic_rag_survey.md` — Liang et al., *Reasoning RAG via System 1 or System 2* (arxiv 2506.10408).
- `raw/30_lau_catrag.md` — Lau et al., *CatRAG / Breaking the Static Graph* (arxiv 2602.01965).

This reference doc sits alongside `12_agentic_retrieval.md`. Doc 12 is the charter (*the agent is the retriever*); this doc is the design-space map.

## The two-tier framing

The gist's most important contribution is separating **indexing** (how data sits at rest) from **execution** (who drives retrieval). They are orthogonal. You can pair any Tier 1 archetype with any Tier 2 paradigm.

### Tier 1 — Indexing archetypes (data structure)

| Archetype | What it is | llmwiki's stance |
|---|---|---|
| **Contextual Hybrid** (Anthropic Contextual Retrieval) | LLM-enriched chunks + BM25 + embeddings | Rejected. The "contextual" enrichment solves a problem we don't have: we don't chunk documents. |
| **RAPTOR** | Tree of recursive LLM summaries over chunk clusters | Rejected as pre-indexing. We do the equivalent manually during ingest: the agent creates `wiki/<topic>/_overview.md` pages as it goes. Supervised hierarchical summarization, not automated. |
| **HippoRAG 2** (PPR over KG) | Entity graph + Personalized PageRank for associative memory | Rejected. The agent walks citations via `follow` and composes multi-step `read` / `search`. No static graph to fight. 7% gain on associative memory is real but targets large corpora we don't have. |
| **GraphRAG / LightRAG** | Community detection + hierarchical summarization | Rejected. Community summaries are useful; we produce them manually as wiki topic pages. The automatic pipeline is overkill at our scale and introduces KG noise that hurts single-hop queries. |
| **CatRAG (2026)** | Query-aware dynamic edge weighting over HippoRAG's KG | Rejected, but instructive. CatRAG explicitly diagnoses the **Static Graph Fallacy** in every other graph approach. Our answer to the fallacy is different: don't build a static graph in the first place — let the agent walk citations dynamically. |
| **Hyperbolic embeddings** | Poincaré-disk embeddings for hierarchical data | Deferred. Interesting for deep taxonomic knowledge, but still maturing and not a fit at personal scale. |

**Conclusion:** every Tier 1 archetype assumes a *static artifact* the agent queries at runtime. llmwiki's indexing archetype is "the wiki itself." The compiled markdown pages + footnote citations + `wiki_claim_provenance` table *are* the index. They are human-readable, navigable by tools, and updated through the guardian's ingest/lint passes — not through a separate pipeline.

### Tier 2 — Execution paradigms (who drives retrieval)

| Paradigm | What it is | llmwiki's stance |
|---|---|---|
| **Agentic Search** (Anthropic / Claude Code) | Model drives search as a reasoning loop. No index. | **Adopted.** This is the llmwiki model. `guide` → `search`/`grep`/`list` → `read` → `follow` → synthesize. |
| **Multi-Agent Orchestrator-Worker** (Anthropic Research) | Lead + parallel subagents + citation validator. External memory handoffs. | **Partially adopted.** The *client* (Claude Code, Claude.ai) owns orchestration; llmwiki exposes re-entrant MCP tools so subagents can work in parallel against the same workspace. Our `wiki_log_entries` + `wiki/log.md` are the external memory the gist's pattern requires. |
| **Iterative Self-Correcting** (IRCoT / Self-RAG / DeepRetrieval) | Interleave reasoning and retrieval in a loop | **Implicit.** The guardian's ingest and query workflows are iterative by construction. We do not formalize Self-RAG style critique; trust goes through user review instead. |
| **Adaptive RAG** (complexity routing) | Route queries by complexity before committing to a strategy | **Declined.** See "Adaptive routing — why we don't need it" below. |
| **MCP as retrieval protocol** | All retrieval modalities unified behind one tool-call interface; agent decides when/what/where | **This IS our story.** See below. |

## Adaptive routing — why we don't need it

The gist lists adaptive routing as *"considered mandatory for production cost control in 2026."* The warning targets pipeline-based systems where you must commit to a retrieval strategy before generation. llmwiki is not such a system.

With agentic search, **the agent is the adaptive router**. It naturally varies effort with query complexity:

- *"What's the date on RFC 0034?"* → one `read("/wiki/entities/rfc-0034.md")`, synthesize, done.
- *"What are Acme's contract terms?"* → `read` overview + a couple of entity pages, synthesize.
- *"Does Acme's new RFC conflict with Q2 agreements?"* → multi-step navigation, multiple `follow` calls, possibly spawning a subagent per topic.

The routing is implicit in the reasoning loop. A separate router layer would add latency, cost, and a policy we'd have to maintain. We do not build one.

## MCP is the retrieval protocol

The gist's final framing is the sharpest: *"retrieval is becoming a tool, not a pipeline."* The agent decides **when** to retrieve, **from what index**, **using what strategy** — and that decision is itself part of the reasoning loop. MCP is the standard that makes this possible by unifying every retrieval modality behind one tool-call interface.

For llmwiki this changes the framing from "we are a knowledge base with an MCP server" to "**we are one of several retrieval tools the agent composes**". Concretely:

1. The agent may call llmwiki's `search` for a concept in the user's personal wiki, then call a separate web search tool, then come back and `read` a follow-up raw source. That's normal composition — we do not own the session.
2. llmwiki's MCP server must play cleanly alongside other MCP servers registered in the same client. No state assumptions, no expectation that we're the first tool called.
3. Our tool descriptions must be explicit enough that the agent picks the right tool for the job. `search` is for "pages about concept X", not "any search"; `grep` is for exact matches; `follow` is for citation traversal. If the tool descriptions are vague, the agent will pick wrong in a multi-tool session.
4. The workspace binding in `08_mcp_integration.md` already handles scoping across multiple llmwiki instances. We extend the same discipline across multiple retrieval tools generally.

## Multi-agent engineering lessons (applied to llmwiki)

The gist extracts five engineering lessons from Anthropic's multi-agent research post. Each maps directly to a concrete requirement on llmwiki's tool surface:

1. **"Short/vague subagent instructions cause duplication and missed coverage — be specific."** → Our MCP tool descriptions must be specific enough that a subagent given "explore the Acme workspace" picks the right tools in the right order. The tool registration code ships examples in every tool description.

2. **"Scale effort to query complexity via embedded rules in prompts."** → The `guide()` response includes guidance on when to do a quick read vs when to go deep. Today's SKILL.md already hints at this; we make it explicit.

3. **"Agents summarise work phases into external memory before context limits; spawn fresh subagents with handoff context."** → `wiki/log.md` + `wiki_log_entries` **is** the external memory. Every ingest/query/lint appends structured data the next agent (or the next subagent) can read via `history()`.

4. **"Subagents write directly to filesystem/memory to avoid coordinator 'telephone' degradation."** → Subagents hit llmwiki's `write` directly, not via the lead agent relaying. Our MCP server is re-entrant by design (see `08_mcp_integration.md`), and every write goes to the same SQLite + filesystem state. No coordinator bottleneck.

5. **"Full production tracing is mandatory — non-determinism makes debugging nearly impossible otherwise."** → `~/.llmwiki/logs/mcp-<date>.jsonl` captures every tool call with `(ts, workspace, tool, args_hash, latency_ms, result)`. This is not optional. Lint passes can replay from it.

## The sharpened claim (again)

llmwiki is **Tier 2 agentic search over a hand-compiled Tier 1 wiki**, served through MCP as one of several retrieval tools the agent may choose to use. We chose agentic search deliberately over every Tier 1 archetype, and we decline adaptive routing because the agent already adapts. The engineering discipline is to make our tool descriptions, external memory, and re-entrancy good enough that a multi-agent client can get real work done against us.
