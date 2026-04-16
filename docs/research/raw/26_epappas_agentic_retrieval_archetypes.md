# Source: epappas — "Agentic-Native Retrieval & Indexing Archetypes (2025–2026)"

- **URL:** https://gist.github.com/epappas/a4428e4dde1f780eae2d899df33e9d5d
- **Author:** @epappas (the user of this project)
- **Created:** 2026-04-15
- **Status:** Secret gist — full verbatim preservation. This is the user's own compiled reference map of the 2025–2026 retrieval landscape and serves as a first-class citation for this project's architecture.

---

# Agentic-Native Retrieval & Indexing Archetypes (2025–2026)

> A reference map of state-of-the-art retrieval paradigms and indexing structures,
> covering the shift from static RAG pipelines to agentic-native retrieval.

---

## Why Naive RAG Falls Short

Classic RAG is a **one-shot, static pipeline**: embed → retrieve top-k → generate.
Core failure modes:

- Knowledge gaps are only discovered _after_ failed retrieval, not before
- Retrieval happens once, with no adaptive follow-up
- No native handling of multi-hop reasoning, tables, charts, or cross-document synthesis
- Chunking destroys context; re-ranking can only partially compensate

Anthropic's own case study: they built a full RAG pipeline for Claude Code
(embeddings, vector DB, chunked retrieval), then benchmarked it against agentic
search (grep, glob, file reads, iterative refinement — no embeddings, no
pre-processing). The agentic approach outperformed "by a lot." They replaced
the RAG pipeline entirely.

---

## Tier 1 — Indexing Archetypes (Data Structure Layer)

These govern how your corpus is represented at rest. Orthogonal to how retrieval
is driven.

### 1. Contextual Hybrid (Anthropic's Contextual Retrieval)

Before embedding, an LLM enriches each chunk with a concise context block
situating it within the broader document. The same enrichment is applied to BM25.
Combining **contextual BM25 + contextual semantic embeddings** yields superior
recall over either alone.

- ✅ Best evolution of classic RAG — low latency, cost-effective
- ✅ Drop-in improvement for existing pipelines
- ❌ Still a fixed pipeline; no iterative refinement

### 2. Tree-Based: RAPTOR

Leaf nodes = chunks. Recursively embedded, clustered via semantic similarity
(Gaussian Mixture Model), summarised by LLM to form parent nodes. Retrieval
queries the hierarchical tree.

- ✅ Top-1 accuracy on structured/hierarchical corpora in multiple benchmarks
- ✅ Most token-efficient of the structure-augmented approaches
- ❌ Static tree structure; suboptimal when query distribution doesn't match clustering axes
- ❌ Recursive LLM summarisation introduces hallucination risk at indexing time

### 3. Neuro-Symbolic KG: HippoRAG 2

Neurobiologically inspired. Builds a Knowledge Graph from entity/relation
extraction, traverses it using **Personalized PageRank (PPR)** to link disparate
facts — simulating associative memory.

- ✅ State-of-the-art multi-hop reasoning performance
- ✅ Significantly fewer indexing tokens than GraphRAG or LightRAG (KG aids retrieval, doesn't expand corpus)
- ✅ Outperforms RAPTOR, GraphRAG, LightRAG on QA and retrieval benchmarks
- ❌ PPR over a static graph suffers from "hub node" semantic drift (see CatRAG below)

### 4. Rich Knowledge Graph: Microsoft GraphRAG & LightRAG

**GraphRAG**: community detection over entities → hierarchical summarisation at
multiple granularities (entity clusters, document clusters, combinations). Global
thematic queries are its strength.

**LightRAG**: dual-level retrieval — low-level (entity-specific) and high-level
(conceptual/thematic) — integrating KG structure with vector retrieval.

- ✅ Best for global/community-level queries ("what are the main themes across this corpus?")
- ✅ LightRAG handles both granularities in one system
- ❌ Very expensive to build and maintain
- ❌ LLM-generated KG noise can degrade single-hop factoid performance

### 5. Dynamic Graph: CatRAG (2026, Frontier)

Addresses the **Static Graph Fallacy** present in all graph-based approaches.
Edge weights in HippoRAG/GraphRAG/LightRAG are fixed at indexing time, causing
high-degree hub nodes to dominate traversal regardless of query intent.

CatRAG applies **query-aware dynamic edge weighting** at retrieval time:

- Symbolic anchoring injects query-specific seed biases
- Dynamic edge scoring amplifies contextually relevant paths
- Key-fact passage weight enhancement steers random walks

- ✅ Outperforms HippoRAG 2 on multi-hop reasoning benchmarks
- ❌ Higher retrieval latency vs. static PPR
- ❌ Still relatively early-stage (early 2026 papers)

### 6. Hyperbolic Embeddings (Emerging)

Standard embeddings exist in Euclidean flat space. Human language and knowledge
are inherently **hierarchical** — flat space cannot represent expanding
parent-child taxonomies without distance distortion.

Poincaré disk / hyperbolic space natively encodes hierarchical structure, enabling
"mixed-hop prediction" across abstraction levels. Vector stores are beginning to
ship native hyperbolic support in 2026.

- ✅ Superior for deep taxonomic / ontological knowledge
- ❌ Limited production tooling today; still maturing

---

## Tier 2 — Agentic-Native Retrieval Paradigms (Execution Layer)

These govern _how_ retrieval is driven. Composable with any indexing archetype
above.

### 1. Agentic Search (Anthropic / Claude Code)

The model itself drives search as a first-class reasoning loop: grep, glob, read,
refine. No pre-built index required.

```
loop:
  decide what to search for
  execute search (grep / glob / file read / API call)
  evaluate results
  if sufficient: synthesise answer
  else: refine query and repeat
```

- ✅ Zero infrastructure: no vector DB, no embedding model, no chunking, no index maintenance
- ✅ Model naturally adapts search strategy based on intermediate findings
- ❌ Ceiling is tightly bound to model capability (frontier models vastly outperform local models on search quality)
- ❌ Higher latency than one-shot retrieval

### 2. Multi-Agent Orchestrator-Worker (Anthropic Research)

Architecture:

- **Lead Researcher agent**: decomposes query → records plan in external memory → spawns parallel subagents
- **Subagents**: each given objective, output format, tool/source guidance, task boundaries
- **Citation Agent**: validates every claim against sources before final output

Key engineering lessons from Anthropic:

- Short/vague subagent instructions cause duplication and missed coverage — be specific
- Scale effort to query complexity via embedded rules in prompts
- Agents summarise work phases into external memory before context limits; spawn fresh subagents with handoff context
- Subagents write directly to filesystem/memory to avoid coordinator "telephone" degradation
- Full production tracing is mandatory — non-determinism makes debugging nearly impossible otherwise

- ✅ Best for deep, open-ended research over heterogeneous sources
- ✅ Parallelism dramatically reduces wall-clock time
- ❌ Complex to operate; stateful long-running agents need checkpointing and rainbow deployments

### 3. Iterative / Self-Correcting Retrieval (IRCoT, Self-RAG, DeepRetrieval)

Rather than a fixed plan, the model interleaves reasoning and retrieval in a loop:

- Identifies knowledge gaps mid-reasoning
- Issues targeted retrieval queries
- Integrates results into evolving chain-of-thought
- DeepRetrieval trains end-to-end via RL (GRPO) using retrieval performance metrics as reward signal — no supervised query datasets needed

System 2 analogy: deliberate, slow, adaptive — vs. System 1 (predefined pipeline =
fast, structured, inflexible).

### 4. Adaptive RAG (Complexity Routing)

Routes queries by complexity before committing to a retrieval strategy:

```
simple factoid → direct LLM answer (no retrieval)
moderate → contextual hybrid chunk retrieval
complex / multi-hop → graph-based or multi-agent
```

Considered mandatory for production cost control in 2026. Reserving heavy compute
strictly for complex tasks yields significant savings without sacrificing quality
on the long tail of simple queries.

### 5. MCP as Retrieval Protocol

Anthropic's Model Context Protocol unifies all retrieval modalities under a single
tool-call interface: vector search, KG traversal, SQL, web search, memory reads.

Architectural implication: retrieval is no longer a pipeline stage — it is one
tool among many that the agent calls when it decides it needs information. The
agent controls _when_, _what_, and _from where_ to retrieve, rather than
retrieval being a mandatory pre-generation step.

---

## Decision Framework

| Scenario | Recommended Approach |
|----------|----------------------|
| Codebase / filesystem navigation | Agentic search (no index) |
| Large doc corpus, simple factoid QA | Contextual hybrid (BM25 + contextual embeddings) |
| Multi-hop reasoning, associative knowledge | HippoRAG 2 + PPR traversal |
| Global thematic / community-level queries | GraphRAG (community detection) |
| Hierarchical / structured domain knowledge | RAPTOR tree |
| High-complexity open-ended research | Multi-agent orchestrator-worker + MCP tools |
| Mixed complexity, cost-constrained production | Adaptive RAG routing over multiple backends |
| Deep taxonomic knowledge with hierarchy | Hyperbolic embeddings (watch this space) |

---

## The Core Architectural Insight

**Retrieval is becoming a tool, not a pipeline.**

The agent decides _when_ to retrieve, from _what_ index, using _what_ strategy —
and that decision is itself part of the reasoning loop. The indexing archetype
becomes a question of what data structure best serves your query distribution,
not a universal architectural choice. MCP standardises the interface; the agent
supplies the intelligence.

---

_Compiled April 2026. Sources: Anthropic Engineering Blog, arXiv 2501.09136
(Agentic RAG Survey), arXiv 2506.10408 (Reasoning Agentic RAG), arXiv 2602.01965
(CatRAG), arXiv 2502.14802 (HippoRAG 2), GraphRAG-Bench (ICLR 2026), LlamaIndex
Agentic Retrieval Guide._
