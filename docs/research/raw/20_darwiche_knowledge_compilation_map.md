# Source: Darwiche & Marquis — "A Knowledge Compilation Map"

- **Venue:** *Journal of Artificial Intelligence Research* (JAIR) Vol. 17, 2002
- **Canonical URL:** https://www.jair.org/index.php/jair/article/view/10311
- **Authors:** Adnan Darwiche, Pierre Marquis
- **Fetched:** 2026-04-15
- **Status:** **PARTIAL — paper PDF not retrievable via WebFetch.**

---

## Retrieval notes

Three URLs attempted and failed in this sandbox:

1. `https://www.jair.org/index.php/jair/article/view/10311` — 403.
2. `https://www.cs.ucla.edu/~darwiche/d70.pdf` — 302 redirect; the redirect target `http://web.cs.ucla.edu/~darwiche/d70.pdf` returned 404.
3. `https://www.jair.org/index.php/jair/article/download/10311/24759/19611` — 403.

The paper is widely cited and the canonical JAIR URL is authoritative. A future retrieval attempt should use a host with access to JAIR's PDF archive.

## What is known about the paper (from established secondary references and the abstract as cited in downstream literature)

- **Core thesis:** knowledge compilation converts a propositional knowledge base into a **target language** in which certain queries (entailment, consistency, model counting, etc.) are tractable. The cost of compilation is paid once, offline; subsequent queries become efficient, often polynomial in the size of the compiled form.
- **The "map":** the paper surveys a set of target languages (NNF, DNNF, d-DNNF, OBDD, FBDD, MODS, PI, IP, etc.) and classifies each by (a) the set of queries it supports in polynomial time and (b) the set of transformations it is closed under.
- **Trade-off:** compilation time and size grow quickly; the choice of target language is a trade-off between how much work happens offline and which queries you need cheap at runtime.

## Why this paper matters for alexandria

The paper is the theoretical grounding for the pattern's core claim — "compile once, query many times." Karpathy's LLM Wiki pattern is an informal instantiation of knowledge compilation: the LLM compiles raw sources (the knowledge base) into a wiki (the target language) so that subsequent queries are cheap both in tokens and in latency. The "lint" operation is the pattern's analogue of maintaining the compiled form under updates — an area the classical compilation literature also studies (incremental compilation, dynamic target languages).

The direct mapping:

| Classical knowledge compilation | Karpathy's LLM Wiki |
|---|---|
| Source knowledge base | `raw/` sources |
| Target language | Structured markdown pages |
| Compilation step | LLM ingest pass |
| Query operation | Q&A over the wiki |
| Tractability guarantee | "Agent finds the relevant page without re-reading the whole corpus" |
| Offline cost | Token spend during ingest |
| Online cost | Token spend during query |

**TODO:** on a future retrieval pass, fetch the full JAIR PDF and populate this file with the verbatim abstract and the formal definition in Section 1.
