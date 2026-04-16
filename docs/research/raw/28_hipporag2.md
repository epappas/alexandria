# Source: Gutiérrez et al. — "From RAG to Memory: Non-Parametric Continual Learning for Large Language Models" (HippoRAG 2)

- **arXiv:** 2502.14802
- **URL:** https://arxiv.org/abs/2502.14802
- **Authors:** Bernal Jiménez Gutiérrez, Yiheng Shu, Weijian Qi, Sizhe Zhou, Yu Su
- **Submitted:** 2025-02-20 (v1); 2025-06-19 (v2)
- **Cited in:** `raw/26_epappas_agentic_retrieval_archetypes.md`
- **Fetched:** 2026-04-15
- **Relation to previous:** Successor to HippoRAG (`raw/17_*`).

---

## Abstract (verbatim)

> "Our ability to continuously acquire, organize, and leverage knowledge is a key feature of human intelligence that AI systems must approximate to unlock their full potential. Given the challenges in continual learning with large language models (LLMs), retrieval-augmented generation (RAG) has become the dominant way to introduce new information. However, its reliance on vector retrieval hinders its ability to mimic the dynamic and interconnected nature of human long-term memory. Recent RAG approaches augment vector embeddings with various structures like knowledge graphs to address some of these gaps, namely sense-making and associativity. However, their performance on more basic factual memory tasks drops considerably below standard RAG. We address this unintended deterioration and propose HippoRAG 2, a framework that outperforms standard RAG comprehensively on factual, sense-making, and associative memory tasks. HippoRAG 2 builds upon the Personalized PageRank algorithm used in HippoRAG and enhances it with deeper passage integration and more effective online use of an LLM. This combination pushes this RAG system closer to the effectiveness of human long-term memory, achieving a 7% improvement in associative memory tasks over the state-of-the-art embedding model while also exhibiting superior factual knowledge and sense-making memory capabilities."

## Key improvement

7% gain on associative-memory tasks over the leading embedding model, **without** the factual-accuracy regression that earlier graph-augmented methods suffered.

## Why this matters for llmwiki

HippoRAG 2 is state-of-the-art for the **multi-hop associative memory** problem — exactly the "given Acme's contract and the new RFC, find everything that's affected" query shape. llmwiki addresses the same query shape differently: instead of building a knowledge graph with PPR traversal, we let the agent walk `wiki_claim_provenance` via the `follow` tool and compose `search` + `read` in a reasoning loop. The paper is what we would graduate to *if* agentic navigation stopped scaling — and the successor paper CatRAG (`raw/30_*`) shows the graph approach itself has an unsolved "static graph fallacy" problem that agentic navigation naturally avoids.
