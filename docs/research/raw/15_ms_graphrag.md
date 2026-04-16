# Source: Edge et al. — "From Local to Global: A Graph RAG Approach to Query-Focused Summarization"

- **arXiv:** 2404.16130
- **URL:** https://arxiv.org/abs/2404.16130
- **Authors:** Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Dasha Metropolitansky, Robert Osazuwa Ness, Jonathan Larson (Microsoft Research)
- **Submitted:** 2024-04-24; latest revision 2025-02-19
- **Fetched:** 2026-04-15
- **Status:** Abstract verbatim + key contributions from the arxiv page.

---

## Abstract (verbatim)

> "The use of retrieval-augmented generation (RAG) to retrieve relevant information from an external knowledge source enables large language models (LLMs) to answer questions over private and/or previously unseen document collections. However, RAG fails on global questions directed at an entire text corpus, such as 'What are the main themes in the dataset?', since this is inherently a query-focused summarization (QFS) task, rather than an explicit retrieval task. Prior QFS methods, meanwhile, do not scale to the quantities of text indexed by typical RAG systems. To combine the strengths of these contrasting methods, we propose GraphRAG, a graph-based approach to question answering over private text corpora that scales with both the generality of user questions and the quantity of source text. Our approach uses an LLM to build a graph index in two stages: first, to derive an entity knowledge graph from the source documents, then to pregenerate community summaries for all groups of closely related entities. Given a question, each community summary is used to generate a partial response, before all partial responses are again summarized in a final response to the user. For a class of global sensemaking questions over datasets in the 1 million token range, we show that GraphRAG leads to substantial improvements over a conventional RAG baseline for both the comprehensiveness and diversity of generated answers."

## Technical contributions

1. **Two-stage LLM-driven graph index:** extract an entity knowledge graph from source documents, then pregenerate community summaries for clusters of related entities.
2. **Query-focused summarization via community summaries:** each community summary generates a partial response; partial responses are then synthesized into a final answer.
3. **Scale target:** datasets in the million-token range, global sensemaking queries.
4. **Reported gains:** "substantial improvements" over vanilla RAG on comprehensiveness and diversity for global questions.
