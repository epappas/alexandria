# Source: Rohit G — LLM Wiki v2 Gist (extensions to Karpathy's pattern)
URL: https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2
Fetched: 2026-04-15
Status: Fetched via WebFetch (summarized extraction)

---

# LLM Wiki v2 - Content Summary

The gist contains a markdown document extending Andrej Karpathy's original LLM Wiki concept with production lessons from building agentmemory.

## Main Sections

**Core Architecture:**
The document builds on three foundational layers: raw sources, wiki pages, and schema. It emphasizes that "stop re-deriving, start compiling" - moving away from retrieval-based systems toward accumulated knowledge.

**Key Additions Beyond Original:**

1. **Memory Lifecycle** - Introduces confidence scoring, supersession of outdated claims, and forgetting curves based on Ebbinghaus principles. Organizes knowledge into tiers: working memory, episodic, semantic, and procedural.

2. **Knowledge Graph Structure** - Moves beyond flat markdown pages to typed relationships ("uses," "depends on," "contradicts") between extracted entities like people, projects, and concepts.

3. **Hybrid Search** - Combines BM25 keyword matching, vector embeddings, and graph traversal rather than relying on single-file indexes beyond ~100 pages.

4. **Automation** - Proposes event-driven hooks for ingestion, session compression, lint operations, and context injection.

5. **Quality Controls** - Includes contradiction resolution, self-healing capabilities, and scoring mechanisms.

6. **Multi-agent Support** - Addresses mesh synchronization, shared versus private knowledge scoping, and coordination.

7. **Crystallization** - Converting exploration sessions into distilled wiki knowledge automatically.

## Critical Commentary

A detailed comment by @gnusupport critiques the lack of implementation specifics regarding confidence scoring mechanics, latency targets, accuracy metrics, versioning, provenance tracking, and production-readiness considerations.
