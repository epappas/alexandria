# Source: Anthropic — "Building a multi-agent research system"

- **URL:** https://www.anthropic.com/engineering/multi-agent-research-system
- **Publisher:** Anthropic (engineering blog)
- **Fetched:** 2026-04-15
- **Status:** Load-bearing direct quotes verbatim.

---

## The core statement against RAG (verbatim)

> "Traditional approaches using Retrieval Augmented Generation (RAG) use static retrieval ... our architecture uses a multi-step search that dynamically finds relevant information, adapts to new findings, and analyzes results to formulate high-quality answers."

This is Anthropic's explicit rejection of static retrieval for research-style questions. The replacement is **dynamic multi-step search**: the agent iterates, adapts, and analyzes as it goes.

## Performance claim (verbatim)

> "a multi-agent system with Claude Opus 4 as the lead agent and Claude Sonnet 4 subagents outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval."

90.2% delta on an *internal research eval*. Not a toy benchmark — Anthropic's own metric for research tasks.

## Subagents as parallel context windows (verbatim)

> "Subagents facilitate compression by operating in parallel with their own context windows, exploring different aspects of the question simultaneously before condensing the most important tokens for the lead research agent."

Subagents are the answer to the "agent reads too much and fills its context" failure mode. Each subagent has its own window, explores one facet, and returns a condensed summary. The lead agent synthesizes summaries — not raw content.

## Speed claim

> "cut research time by up to 90% for complex queries"

Through concurrent tool usage across agents.

## Why this matters for llmwiki

This is the single most important public statement from Anthropic aligned with our thesis. Three direct implications:

1. **Reject "static retrieval" as the organizing principle.** llmwiki's `search` tool is not a retriever. It's a primitive the agent uses as one of several moves. The retrieval algorithm IS the agent's loop.
2. **Multi-step is the shape of good retrieval.** A query becomes a plan becomes a series of reads. This is already how the ingest workflow works — we just need to make it equally explicit for query.
3. **Subagents for wide exploration.** When a user asks a cross-cutting question, the guardian should be able to spawn a subagent per topic, each with its own context window, and synthesize the summaries. This requires that our MCP tool surface be safely re-entrant per subagent — a design constraint we need to respect.
