# Source: Anthropic — "Introducing Contextual Retrieval"

- **URL:** https://www.anthropic.com/news/contextual-retrieval
- **Publisher:** Anthropic (news / engineering)
- **Fetched:** 2026-04-15
- **Status:** Quotes verbatim. Included for completeness — this post is Anthropic's *pro-RAG* piece (for contexts where RAG is appropriate), but even it concedes the core problem.

---

## The admission about traditional RAG (verbatim)

> "Traditional RAG systems have a significant limitation: they often destroy context."

Anthropic's own engineers, in their own pro-retrieval post, state the problem plainly. Chunks torn out of context become ambiguous: "The company's revenue grew by 3%" means nothing without knowing which company and which quarter.

## Their fix — contextual chunks (verbatim)

The technique is **contextual embeddings**: prepend a per-chunk explanatory preamble to each chunk before embedding, so the chunk carries its own context. Same idea for BM25 (lexical).

- Original chunk: *"The company's revenue grew by 3% over the previous quarter."*
- Contextualized: *"This chunk is from an SEC filing on ACME corp's performance in Q2 2023; the previous quarter's revenue was $314 million. The company's revenue grew by 3% over the previous quarter."*

## Eval results (verbatim fragments)

- Contextual Embeddings alone: 35% failure-rate reduction (5.7% → 3.7%).
- Contextual Embeddings + BM25: 49% reduction (5.7% → 2.9%).
- With reranking added: 67% reduction (5.7% → 1.9%).

## Hybrid retrieval note (verbatim)

> "Embeddings+BM25 is better than embeddings on their own."

BM25 excels where embeddings fail — precise term matches like error codes. The two techniques "balance precise term matching with broader semantic understanding."

## Why this matters for alexandria

Three things:

1. **The confirmation.** Even Anthropic's RAG-positive post admits *"traditional RAG systems ... often destroy context."* That is the point our architecture starts from.
2. **Where RAG is the right tool.** Contextual Retrieval is designed for **large corpora a single agent cannot navigate by hand**. If a knowledge base has millions of chunks, someone must narrow before reading. alexandria targets hundreds to low thousands — a regime where the agent can navigate without embeddings.
3. **The hybrid rule is still good advice at any scale.** Keyword (BM25 / FTS5) plus pattern (grep) plus structural (glob / list) plus read. We use all three already. We do not use embeddings because at our scale we do not need them — the agent can reach every page through navigation primitives.

The explicit architectural move: we do not scaffold pgvector. We commit to FTS5 (keyword / BM25 equivalent) + glob (structural) + pattern search + read as the primitives, and we make the agent the retriever.
