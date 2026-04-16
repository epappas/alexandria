# Source: Singh et al. — "Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG"

- **arXiv:** 2501.09136
- **URL:** https://arxiv.org/abs/2501.09136
- **Authors:** Aditi Singh, Abul Ehtesham, Saket Kumar, Tala Talaei Khoei, Athanasios V. Vasilakos
- **Submitted:** 2025-01-15 (v1); last revised 2026-04-01 (v4)
- **Cited in:** `raw/26_epappas_agentic_retrieval_archetypes.md` as a source
- **Fetched:** 2026-04-15

---

## Abstract (verbatim opening)

> "Large Language Models (LLMs) have advanced artificial intelligence by enabling human-like text generation and natural language understanding. However, their reliance on static training data limits their ability to respond to dynamic, real-time queries, resulting in outdated or inaccurate outputs. Retrieval-Augmented Generation (RAG) has emerged as a solution, enhancing LLMs by integrating real-time data retrieval to provide contextually relevant and up-to-date responses."

## Taxonomy (verbatim characterization)

> "a principled taxonomy of Agentic RAG architectures based on **agent cardinality, control structure, autonomy, and knowledge representation**."

## The core claim against traditional RAG (verbatim)

Traditional RAG systems are *"constrained by static workflows and lack the adaptability required for multi-step reasoning and complex task management."* Agentic RAG overcomes this by embedding *"autonomous AI agents into the RAG pipeline"* utilizing *"agentic design patterns: reflection, planning, tool use, and multi-agent collaboration."*

## Open research challenges (named)

Evaluation, coordination, memory management, efficiency, governance.

## Why this matters for alexandria

Confirms the agentic-retrieval direction at the survey level. Four design axes (cardinality / control / autonomy / knowledge representation) are a useful lens for alexandria:

- **Cardinality:** single guardian per session, with optional subagents spawned by the MCP client.
- **Control:** the agent drives; we expose tools, not pipelines.
- **Autonomy:** supervised — the user triggers ingest; the agent executes.
- **Knowledge representation:** markdown on disk, not a vector store.
