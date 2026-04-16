# Reference: Graph RAG Literature (GraphRAG, LightRAG, HippoRAG)

**Sources:** `raw/15_ms_graphrag.md`, `raw/16_lightrag.md`, `raw/17_hipporag.md`

**Note (revised):** An earlier version of this doc framed alexandria as "personal-scale Graph RAG." That framing concedes too much. alexandria is **not Graph RAG**. The retrieval model is *agentic navigation* — the agent composes primitives (`list`, `grep`, `search`, `read`, `follow`) in a multi-step reasoning loop. Graph RAG is a *contrasting* approach: a static index built from entity extraction + community summarization, consulted at query time. See `12_agentic_retrieval.md` for the authoritative statement of our retrieval model.

What these three papers still contribute is the **failure analysis of naive chunk RAG** and the **structural ideas** (community summaries, hierarchical indexing) we borrow for orientation documents — but we execute those ideas through agent navigation, not through a pre-built retrieval pipeline.

Three 2024 papers that represent one direction the field took to address naive RAG's failures. alexandria takes a different direction — agentic navigation — but we read them to understand the problem and to borrow the structural insights.

## What all three papers agree on

1. **Flat vector RAG fails on global questions.** Retrieving k chunks by embedding similarity cannot answer "what are the main themes here?" because the answer is not in any chunk.
2. **A graph / structured index is the fix.** Entities and their relationships become first-class. Retrieval walks the graph instead of scoring chunks in isolation.
3. **Community / hierarchy matters.** GraphRAG's community summaries, LightRAG's dual-level retrieval, HippoRAG's PPR over a knowledge graph — all three add structure above the chunk layer.
4. **Pregeneration pays.** Doing LLM work offline (build the graph, summarize communities) is cheaper than doing it per-query.

Every one of these observations is already in Karpathy's pattern. The difference is that the papers optimize for **enterprise scale** (millions of tokens, thousands of documents) while Karpathy's pattern optimizes for **personal scale** (~100 articles, ~400K words).

## GraphRAG (Edge et al. 2024, Microsoft)

**The move:** LLM → entity graph → community detection → pregenerated community summaries → query → summaries-of-summaries.

**Why it matters to us:** GraphRAG explicitly frames its target as "global sensemaking questions over datasets in the 1 million token range." That is exactly the **lower** bound where Karpathy's pattern starts to hit its scale cliff. GraphRAG is what we graduate to *if* a user's workspace grows past the point where the guardian can no longer keep the whole wiki in reach.

**What we copy:**
- Community summaries = our `wiki/<topic>/_overview.md` pattern (implicit in the Astro-Han SKILL.md).
- Entity extraction = the `wiki/entities/` directory lucasastorian's reference prompt teaches the agent to maintain.

**What we do differently:**
- We don't build the graph automatically. The guardian *is* the graph builder — every `write(create)` + `str_replace` is a manual graph operation, supervised by the user's prompts.
- Our "compilation" step is higher-level (synthesized markdown pages) vs GraphRAG's entity-level extraction.

## LightRAG (Guo et al. 2024, HKU)

**The move:** dual-level retrieval (low-level entity + high-level concept), incremental updates without full reindex, graph + vector hybrid.

**Why it matters to us:** the **incremental update** property is load-bearing. Our source adapters sync continuously; we cannot afford to reindex everything on every new document. LightRAG proves you can get near-GraphRAG quality while keeping incremental updates cheap.

**What we copy:**
- Incremental re-sync via content hashing — already in our adapter spec (and traces back further to the atomicmemory compiler's SHA-256 trick).
- Dual-level access — our `search` tool has both `list` (structural browsing) and `search` (FTS5 content match), which is a crude but working version of dual-level retrieval.

## HippoRAG (Gutiérrez et al. 2024, NeurIPS)

**The move:** model the retrieval problem after the hippocampus. Run Personalized PageRank over a knowledge graph to find multi-hop answers in a single step.

**Why it matters to us:** HippoRAG reports **10–30× cost reduction and 6–13× speed-up** vs iterative retrieval on multi-hop queries. The implication: graph-walk retrieval beats iterative re-query on cost *and* latency when multi-hop reasoning is needed.

**What we watch for, post-MVP:**
- When our guardian needs to answer "does the Acme contract conflict with the new infra RFC?" the answer requires walking from one concept page to another through cross-references. Today the agent does this via manual `read` calls. When workspaces grow, a PPR-style tool could short-circuit the walk.
- `history()` over `wiki_log_entries` is already a graph query in disguise — it follows the `touched_documents` list from one log entry to the next.

## What the three papers tell us we got right

1. **Compile offline, query online.** All three papers, same lesson. We enforce it by separating sync (background) from ingest (agent-driven).
2. **Structure beats flat embeddings.** We store markdown pages with explicit cross-references and footnotes rather than an undifferentiated embedding column.
3. **Pregeneration pays.** Our mandatory `overview.md` + `index.md` are the same idea as GraphRAG's community summaries — pregenerated answers to frequent questions.
4. **Incremental updates are table stakes.** The Bush-level "compile once" idea is aspirational in practice; real systems need cheap updates. We ship content-hash-based re-sync from day one.

## What the three papers tell us we can **defer**

1. **Automatic entity extraction.** GraphRAG and HippoRAG both do this automatically. We don't need to — the guardian does it as part of ingest, and the user reviews the result. We can add auto-extraction later as a pre-pass to reduce the guardian's token spend.
2. **Personalized PageRank retrieval.** Overkill at personal scale. Mark it as a trigger condition in `07_open_questions.md` — when a workspace exceeds N pages and multi-hop queries start failing, this is the fix.
3. **Dense community clustering.** Our topic subdirectories are a manual version of the same thing. Automated clustering is a v2 feature.

## The sharpened claim

alexandria is **agentic search over a compiled wiki**, not Graph RAG. The two approaches diverge on the core question: *who drives retrieval?* Graph RAG answers "a static multi-stage pipeline" and invests engineering in making the pipeline smart. alexandria answers "the agent itself" and invests engineering in making the primitives and orientation documents sharp.

At enterprise scale (millions of tokens, automated ingest, no human per query) Graph RAG wins because human-in-the-loop doesn't scale. At personal scale (tens to a few thousand pages, supervised ingest, human-directed queries) agentic search wins because the agent can actually reach every relevant page through navigation, and supervision buys high trust (every claim cited, every update logged, every write validated).

Both are valid points in the knowledge compilation design space. We chose agentic search deliberately and we do not scaffold a fallback vector path — see `12_agentic_retrieval.md`.
