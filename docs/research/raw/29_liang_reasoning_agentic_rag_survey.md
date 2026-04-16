# Source: Liang et al. — "Reasoning RAG via System 1 or System 2: A Survey on Reasoning Agentic Retrieval-Augmented Generation for Industry Challenges"

- **arXiv:** 2506.10408
- **URL:** https://arxiv.org/abs/2506.10408
- **Authors:** Jintao Liang, Gang Su, Huifeng Lin, You Wu, Rui Zhao, Ziyue Li
- **Submitted:** 2025-06-12
- **Cited in:** `raw/26_epappas_agentic_retrieval_archetypes.md`
- **Fetched:** 2026-04-15

---

## Abstract (verbatim)

> "Retrieval-Augmented Generation (RAG) has emerged as a powerful framework to overcome the knowledge limitations of Large Language Models (LLMs) by integrating external retrieval with language generation. While early RAG systems based on static pipelines have shown effectiveness in well-structured tasks, they struggle in real-world scenarios requiring complex reasoning, dynamic retrieval, and multi-modal integration. To address these challenges, the field has shifted toward Reasoning Agentic RAG, a paradigm that embeds decision-making and adaptive tool use directly into the retrieval process. In this paper, we present a comprehensive review of Reasoning Agentic RAG methods, categorizing them into two primary systems: predefined reasoning, which follows fixed modular pipelines to boost reasoning, and agentic reasoning, where the model autonomously orchestrates tool interaction during inference. We analyze representative techniques under both paradigms, covering architectural design, reasoning strategies, and tool coordination. Finally, we discuss key research challenges and propose future directions to advance the flexibility, robustness, and applicability of reasoning agentic RAG systems."

## The System 1 / System 2 split

Two categories of reasoning agentic RAG:

1. **Predefined reasoning (System 1)** — fixed modular pipelines. Fast, structured, inflexible.
2. **Agentic reasoning (System 2)** — the model autonomously orchestrates tools during inference. Deliberate, slow, adaptive.

## Why this matters for llmwiki

llmwiki is squarely in the **agentic reasoning (System 2)** camp. The user's gist (`raw/26_*`) extends this framing with IRCoT / Self-RAG / DeepRetrieval as examples. The survey validates the direction at the academic level — *"the field has shifted toward Reasoning Agentic RAG"* — and names the System 1 / System 2 distinction that maps cleanly onto "static pipeline vs agentic loop."
