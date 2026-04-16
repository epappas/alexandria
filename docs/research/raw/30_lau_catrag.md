# Source: Lau et al. — "Breaking the Static Graph: Context-Aware Traversal for Robust Retrieval-Augmented Generation" (CatRAG)

- **arXiv:** 2602.01965
- **URL:** https://arxiv.org/abs/2602.01965
- **Authors:** Kwun Hang Lau, Fangyuan Zhang, Boyu Ruan, Yingli Zhou, Qintian Guo, Ruiyuan Zhang, Xiaofang Zhou
- **Submitted:** 2026-02-02
- **Cited in:** `raw/26_epappas_agentic_retrieval_archetypes.md`
- **Fetched:** 2026-04-15

---

## Abstract (verbatim)

> "Recent advances in Retrieval-Augmented Generation (RAG) have shifted from simple vector similarity to structure-aware approaches like HippoRAG, which leverage Knowledge Graphs (KGs) and Personalized PageRank (PPR) to capture multi-hop dependencies. However, these methods suffer from a 'Static Graph Fallacy': they rely on fixed transition probabilities determined during indexing. This rigidity ignores the query-dependent nature of edge relevance, causing semantic drift where random walks are diverted into high-degree 'hub' nodes before reaching critical downstream evidence. Consequently, models often achieve high partial recall but fail to retrieve the complete evidence chain required for multi-hop queries. To address this, we propose CatRAG, Context-Aware Traversal for robust RAG, a framework that builds on the HippoRAG 2 architecture and transforms the static KG into a query-adaptive navigation structure. We introduce a multi-faceted framework to steer the random walk: (1) Symbolic Anchoring, which injects weak entity constraints to regularize the random walk; (2) Query-Aware Dynamic Edge Weighting, which dynamically modulates graph structure, to prune irrelevant paths while amplifying those aligned with the query's intent; and (3) Key-Fact Passage Weight Enhancement, a cost-efficient bias that structurally anchors the random walk to likely evidence. Experiments across four multi-hop benchmarks demonstrate that CatRAG consistently outperforms state of the art baselines. Our analysis reveals that while standard Recall metrics show modest gains, CatRAG achieves substantial improvements in reasoning completeness, the capacity to recover the entire evidence path without gaps. These results reveal that our approach effectively bridges the gap between retrieving partial context and enabling fully grounded reasoning."

## The Static Graph Fallacy (verbatim definition)

> "fixed transition probabilities determined during indexing. This rigidity ignores the query-dependent nature of edge relevance, causing semantic drift where random walks are diverted into high-degree 'hub' nodes before reaching critical downstream evidence."

## Why this matters for llmwiki

CatRAG is load-bearing evidence that **even state-of-the-art graph RAG has structural problems**. The "static graph fallacy" names a real failure mode: high-degree hub nodes absorb random walks regardless of query intent. CatRAG's fix is to make the graph dynamic, but the fix itself concedes the diagnosis — static indexes fight against query-time context.

Agentic navigation **avoids the problem by construction**. The agent's reasoning loop is query-adaptive by definition: on every step it decides what to read next based on what it has read so far. There is no static transition probability to fight. The cost is higher latency and model-capability dependence; the benefit is that scaling is a matter of better primitives (grep, follow, subagents) rather than better graph algorithms.

This paper is the best single justification for llmwiki's no-graph, no-vector, agent-as-retriever commitment. When the SOTA graph approach admits its own structural flaw and proposes query-aware dynamic edge weighting as the fix, the principled move is to let the agent *be* the dynamic weighting — which is what agentic retrieval has always been.
