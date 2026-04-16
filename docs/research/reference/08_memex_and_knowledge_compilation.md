# Reference: Memex (Bush, 1945) + Knowledge Compilation (Darwiche & Marquis, 2002)

**Sources:** `raw/14_bush_as_we_may_think.md`, `raw/20_darwiche_knowledge_compilation_map.md`

Two intellectual ancestors, eighty and twenty-four years old respectively. Both are load-bearing for the pattern's core claim: that a personal knowledge store should be built once and consulted cheaply many times.

## Bush 1945 — the associative store

Three direct quotes from section 6 of *As We May Think*:

> "The human mind does not work that way. It operates by association. With one item in its grasp, it snaps instantly to the next that is suggested by the association of thoughts."

> "Selection by association, rather than by indexing, may yet be mechanized."

> "A memex is a device in which an individual stores all his books, records, and communications, and which is mechanized so that it may be consulted with exceeding speed and flexibility. It is an enlarged intimate supplement to his memory."

Bush's thesis, eighty years before alexandria, is that (a) the scientific record already exceeds human ability to find what exists in it, (b) the fix is not more cataloguing but **associative access**, and (c) the right unit is a **personal, private** store that captures one individual's thinking and its connections.

Every invariant in our architecture — markdown as the associative substrate, dense cross-links, one-user-one-store, the rejection of hierarchical taxonomies — is an instance of Bush's design 80 years later.

The specific mapping:

| Bush (1945) | alexandria (2026) |
|---|---|
| Memex — personal associative device | `~/.alexandria/workspaces/<slug>/` |
| "Enlarged intimate supplement to memory" | The guardian agent's wiki |
| Trails — explicit associative paths | Wiki cross-links + footnote citations |
| "Stores all his books, records, and communications" | Pluggable source adapters |
| Association over indexing | FTS5 + cross-links, not rigid taxonomies |

**What this justifies for us:** the architectural rejection of deep hierarchical directory trees. The Astro-Han `SKILL.md` enforces "one topic subdir level only" — we inherit that, and now we can cite Bush for why.

## Darwiche & Marquis 2002 — compile once, query cheap

Paper retrieval failed in this sandbox (see `raw/20_*.md` for the URLs attempted). The core thesis is well-established:

- A knowledge base is **compiled offline** into a **target language** (NNF, DNNF, d-DNNF, OBDD, etc.).
- Each target language supports a specific set of **tractable queries** — polynomial in the size of the compiled form.
- The "map" classifies target languages by (query set they support, transformations they're closed under, succinctness trade-off).
- Compilation is expensive; queries are cheap. The strategy only makes sense when queries outnumber compilations.

**The direct mapping to Karpathy's pattern:**

| Classical knowledge compilation | Karpathy's LLM Wiki |
|---|---|
| Source KB (propositional) | `raw/` source documents |
| Target language | Structured markdown pages |
| Compilation step | LLM ingest pass |
| Query operation | Q&A over the wiki |
| Tractability guarantee | "Agent finds the right page without re-reading the corpus" |
| Offline cost | Token spend during ingest |
| Online cost | Token spend during query |
| Incremental compilation | Cascade updates + the lint pass |

Karpathy uses the word "compile" literally in his tweet. That is not a loose metaphor — it is the specific CS-theoretic operation Darwiche & Marquis formalized. The LLM Wiki pattern is the informal, natural-language instance of their framework.

**What this justifies for us:**

1. **The ingest/query split is theoretically principled**, not just a convenient decomposition. Ingest = compilation. Query = tractable query over the compiled form.
2. **Token budgets should be skewed toward ingest**, because that's when the hard work happens. Query should be cheap precisely because ingest was expensive.
3. **The lint pass corresponds to maintaining the compiled form under updates** — a well-studied problem in incremental knowledge compilation. When sources change, the compilation must be updated without recomputing everything.
4. **Different workspaces can use different "target languages"** — a research workspace might emphasize concept pages (DNNF-like: many distinct atoms), a customer workspace might emphasize entity pages (OBDD-like: canonicalized). The template system we have for workspaces is, in Darwiche's terms, a choice of target language.

## The two together

Bush gives us the *shape* (personal, associative, private, dense). Darwiche & Marquis give us the *mechanism* (offline compilation, tractable query language). Karpathy's pattern is the synthesis: the LLM plays the role of the compiler, markdown plays the role of the target language, and the human plays the role of the user asking queries.

The architecture's core claim — that this is fundamentally different from RAG — is defensible precisely because it sits in the knowledge compilation tradition, not the retrieval-and-generate tradition. RAG has no compilation step; alexandria's whole point is that the compilation step is load-bearing.
