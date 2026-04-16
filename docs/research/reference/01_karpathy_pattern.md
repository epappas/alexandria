# Reference: Karpathy's Original LLM Wiki Pattern

**Sources:** `raw/00_karpathy_tweet.md` (full verbatim tweet), `raw/01_karpathy_gist_llmwiki.md`

## The authoritative primary source

Karpathy's X post from 2026-04-02 is now retrieved in full via the fxtwitter proxy. Load-bearing direct quotes:

> *"using LLMs to build personal knowledge bases for various topics of research interest. In this way, a large fraction of my recent token throughput is going less into manipulating code, and more into manipulating knowledge (stored as markdown and images)."*

> *"I index source documents (articles, papers, repos, datasets, images, etc.) into a raw/ directory, then I use an LLM to incrementally 'compile' a wiki, which is just a collection of .md files in a directory structure."*

> *"Important to note that the LLM writes and maintains all of the data of the wiki, I rarely touch it directly."*

> *"once your wiki is big enough (e.g. mine on some recent research is ~100 articles and ~400K words), you can ask your LLM agent all kinds of complex questions against the wiki, and it will go off, research the answers, etc. I thought I had to reach for fancy RAG, but the LLM has been pretty good about auto-maintaining index files and brief summaries of all the documents and it reads all the important related data fairly easily at this ~small scale."*

> *"Often, I end up 'filing' the outputs back into the wiki to enhance it for further queries. So my own explorations and queries always 'add up' in the knowledge base."*

> *"I've run some LLM 'health checks' over the wiki to e.g. find inconsistent data, impute missing data (with web searchers), find interesting connections for new article candidates, etc."*

> *"TLDR: raw data from a given number of sources is collected, then compiled by an LLM into a .md wiki, then operated on by various CLIs by the LLM to do Q&A and to incrementally enhance the wiki, and all of it viewable in Obsidian. You rarely ever write or edit the wiki manually, it's the domain of the LLM."*

> *"I think there is room here for an incredible new product instead of a hacky collection of scripts."*

That last line is the mandate for this entire project.

## Load-bearing ideas

1. **Compile, don't retrieve.** The wiki is a *compiled* artifact, not a search substrate. "Compile" is the word Karpathy uses himself. This reframes the pattern away from RAG and toward classical knowledge compilation — see `08_memex_and_knowledge_compilation.md`.

2. **Three strict layers.** `raw/` (immutable sources), the compiled wiki (markdown pages owned by the LLM), and a schema contract the agent reads before acting.

3. **The contract — verbatim.** *"The LLM writes and maintains all of the data of the wiki, I rarely touch it directly."* Not a design preference — the stated working model.

4. **Three operations only.**
   - **Ingest** — compile new sources into pages, cascading updates.
   - **Q&A (query)** — answer from the wiki; optionally file answers back as new pages ("explorations always add up").
   - **Linting** — health-check the wiki for inconsistencies, stale data, missing links, and new article candidates.

5. **Special files.** `index.md` and `log.md` are structural. The `wiki/log.md` append-only pattern is the agent's own self-awareness mechanism.

6. **Why it works — verbatim.** Karpathy says the LLM "has been pretty good about auto-maintaining index files and brief summaries of all the documents." LLMs don't tire of bookkeeping; that is the entire engineering thesis.

7. **Reported scale.** ~100 articles, ~400K words of compiled wiki on personal research. Not a hypothetical; the production instance Karpathy runs.

8. **Tooling he actually uses.** Obsidian as the IDE. Obsidian Web Clipper for web→markdown ingest. Marp for slide output. A small "vibe-coded" search engine over the wiki accessible via CLI. Matplotlib for generated images.

9. **Output is multi-format.** Not just text answers — rendered markdown, slide decks, matplotlib images. The wiki is both the read side *and* the write side for derived artifacts.

10. **Roadmap Karpathy mentions.** Synthetic data generation + fine-tuning to bake the wiki into model weights. Explicitly out of scope for MVP; noted for reference.

## Community reception (from `01_karpathy_gist_llmwiki.md`)

500+ comments on the gist, roughly:
- **Supporters** report 200-page wikis built from 35 sources in about an hour with minimal prompt modification.
- **Skeptics** argue markdown does not scale as a knowledge-graph substrate (no foreign keys), hallucination risk grows with wiki age, and cascade updates are a hidden maintenance tax.
- **Extensions** (OmegaWiki, Synthadoc, Graphite Atlas, AgentWiki) push toward typed entities, graph structure, and lint automation — same direction as the v2 gist.

## What this means for us

The pattern has a named inventor, a stated contract, a quoted scale, a stated toolchain, and an explicit invitation ("room here for an incredible new product") to turn it into a real product. We are not inferring the design — Karpathy gave us the spec. Our job is to enforce it as a service and add pluggable sources, self-awareness, and MCP integration.
