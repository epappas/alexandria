# Source: Gutiérrez et al. — "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models"

- **arXiv:** 2405.14831
- **URL:** https://arxiv.org/abs/2405.14831
- **Venue:** NeurIPS 2024
- **Authors:** Bernal Jiménez Gutiérrez, Yiheng Shu, Yu Gu, Michihiro Yasunaga, Yu Su (Ohio State / Stanford)
- **Submitted:** 2024-05-23; latest revision 2025-01-14
- **Fetched:** 2026-04-15
- **Status:** Abstract opening verbatim + technical contributions.

---

## Abstract (verbatim opening)

> "In order to thrive in hostile and ever-changing natural environments, mammalian brains evolved to store large amounts of knowledge about the world and continually integrate new information while avoiding catastrophic forgetting."

The authors present a retrieval framework addressing LLM limitations in integrating new experiences post-training.

## Technical contributions

1. **Hippocampal indexing analogy** — mirrors human memory by mimicking distinct roles of the neocortex and hippocampus. "Orchestrates LLMs, knowledge graphs, and the Personalized PageRank algorithm."
2. **Personalized PageRank retrieval** — identifies relevant information nodes via PPR on a knowledge graph, enabling multi-hop reasoning without iterative retrieval.
3. **Performance** — up to 20% gains over existing methods on multi-hop benchmarks. Single-step retrieval comparable to iterative approaches while reducing cost 10–30× and improving speed 6–13×.
