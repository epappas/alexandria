# Research References

One reference document per raw source (or per coherent cluster of sources). Each reference distills the *load-bearing* ideas — the ones that actually influence our design choices — so readers of the architecture docs never need to crawl the raw material.

Ordered roughly by importance for our implementation:

| # | Reference | Raw source(s) | Why it matters |
|---|---|---|---|
| 01 | [Karpathy's LLM Wiki pattern](01_karpathy_pattern.md) | `raw/00_*` (full verbatim tweet), `raw/01_*` | The canonical 3-layer architecture and the stated contract. Direct quotes from the tweet. |
| 02 | [lucasastorian/llmwiki reference implementation](02_lucasastorian_impl.md) | `raw/04_*`, `raw/12_*` | Multi-tenant FastAPI + MCP + Postgres implementation — closest Python template we can study. |
| 03 | [Astro-Han SKILL.md workflow specification](03_astrohan_skill.md) | `raw/05_*`, `raw/07_*`, `raw/13_*` | The precise ingest/query/lint workflow, cascade rules, lint categories, file templates. |
| 04 | [atomicmemory llm-wiki-compiler pipeline](04_atomicmemory_compiler.md) | `raw/06_*` | Two-phase concept extraction pipeline and SHA-256 incremental recompile model. |
| 05 | [v2 extensions (rohitg00) — memory, graph, lint](05_llmwiki_v2_extensions.md) | `raw/03_*` | Confidence, contradiction resolution, knowledge graph — future-looking. |
| 06 | [Practitioner guides (MindStudio / Starmorph / DAIR.AI)](06_practitioner_guides.md) | `raw/02_*`, `raw/09_*`, `raw/10_*` | Obsidian vault layout, QMD semantic-search tip, scale-cliff data points. |
| 07 | [VentureBeat & Antigravity — the "why"](07_why_post_code.md) | `raw/08_*`, `raw/11_*` | Paradigm framing. Obsidian CEO's vault-separation warning. |
| 08 | [Memex + Knowledge Compilation](08_memex_and_knowledge_compilation.md) | `raw/14_*` (Bush), `raw/20_*` (Darwiche & Marquis) | The 80-year intellectual ancestry. Why "compile once, query cheap" is theoretically principled, not just convenient. |
| 09 | [Graph RAG literature](09_graph_rag_literature.md) | `raw/15_*` (GraphRAG), `raw/16_*` (LightRAG), `raw/17_*` (HippoRAG) | The formal, enterprise-scale cousin of Karpathy's pattern. Validates our design choices and flags what we defer. |
| 10 | [LLM memory architectures](10_llm_memory_architectures.md) | `raw/18_*` (MemGPT), `raw/19_*` (Generative Agents) | The literature on LLMs with persistent memory — closest prior work to the guardian's self-awareness story. |
| 11 | [Evergreen notes (Matuschak)](11_evergreen_notes.md) | `raw/21_*` | The five principles. Each maps directly to a llmwiki lint rule. The user-facing framing of "better thinking over better note-taking." |
| 12 | [Agentic retrieval — the agent is the retriever](12_agentic_retrieval.md) | `raw/22_*`, `raw/23_*`, `raw/24_*`, `raw/25_*`, plus `raw/00_*` | Anthropic's and Karpathy's authoritative rejection of static RAG in favor of agent-driven multi-step navigation. The charter for llmwiki's retrieval model. |
| 13 | [The agentic retrieval design space](13_agentic_retrieval_design_space.md) | `raw/26_*` (epappas gist), `raw/27_*` (Agentic RAG Survey), `raw/28_*` (HippoRAG 2), `raw/29_*` (Reasoning Agentic RAG Survey), `raw/30_*` (CatRAG) | The Tier 1 (indexing) × Tier 2 (execution) orthogonality. Maps every state-of-the-art archetype to llmwiki's stance. Names "MCP is the retrieval protocol" and explains why we don't need adaptive routing. |
| 14 | [MemPalace — sibling project, three adoptions](14_mempalace.md) | `raw/36_mempalace.md` | A deep comparison with the mempalace project: shared values (local-first, MCP-first, Zettelkasten), principled divergences (vectors, verbatim chunking, ER graph), three adoptions (tiered wake-up, conversation-transcript ingestion, auto-save hooks), three deferred ideas. The sibling-not-competitor framing. |

---

## Platform-constraint raw research (operational facts, no reference doc)

These raw files are cited directly from architecture docs rather than through a reference synthesis. They record verified platform facts that drive specific design decisions.

| Raw | Cited in | What it establishes |
|---|---|---|
| [`raw/31_nitter_status_2026.md`](../raw/31_nitter_status_2026.md) | `architecture/09_subscriptions_and_feeds.md` | Nitter still maintained but now requires real Twitter session tokens → justifies the three-tier Twitter adapter strategy |
| [`raw/32_slack_free_tier_retention.md`](../raw/32_slack_free_tier_retention.md) | `architecture/10_event_streams.md` | Slack free plan — 90-day access, 1-year deletion → defines the hard limit on historical Slack ingest |
| [`raw/33_github_events_api.md`](../raw/33_github_events_api.md) | `architecture/10_event_streams.md` | GitHub Events API caps at 30 days / 300 events → drives the two-track (backfill via REST, live via Events/webhooks) GitHub adapter strategy |
| [`raw/34_google_calendar_api.md`](../raw/34_google_calendar_api.md) | `architecture/10_event_streams.md` | `syncToken` incremental-sync primitive available → enables cheap 5-minute polling of the calendar adapter |
| [`raw/35_anthropic_prompt_caching.md`](../raw/35_anthropic_prompt_caching.md) | `architecture/11_inference_endpoint.md` | Cache read = 0.1× base cost, 4096-token minimum for Opus 4.6, hierarchy `tools → system → messages` → drives the caching strategy that keeps scheduled synthesis affordable |
