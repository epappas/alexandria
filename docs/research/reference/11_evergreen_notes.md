# Reference: Evergreen Notes (Matuschak)

**Source:** `raw/21_matuschak_evergreen_notes.md`

Andy Matuschak's "evergreen notes" is the most load-bearing personal knowledge management framing for llmwiki. Not a paper — a set of five principles that describe what a personal note should look like *to be worth keeping over years*.

## The five principles (verbatim)

1. **Evergreen notes should be atomic.**
2. **Evergreen notes should be concept-oriented.**
3. **Evergreen notes should be densely linked.**
4. **Prefer associative ontologies to hierarchical taxonomies.**
5. **Write notes for yourself by default, disregarding audience.**

Definition (paraphrased): evergreen notes are written and organized to **evolve, contribute, and accumulate over time, across projects** — the opposite of transient, project-bound notes.

## Why these are the architecture's acceptance criteria

Each principle maps onto a hard-enforced invariant in llmwiki:

| Matuschak principle | llmwiki enforcement |
|---|---|
| Atomic — one concept per note | `write` validates wiki pages are scoped to a single concept via the template check; the guardian's prompt forbids "dumping" whole sources into one page |
| Concept-oriented — named after the idea | The Astro-Han SKILL.md rule: wiki pages are named after the concept, not the raw source file. We inherit and enforce this. |
| Densely linked | Cascade updates on ingest (mandatory). Lint auto-fixes missing see-also links. Provenance index (`wiki_claim_provenance`) makes linkage queryable. |
| Associative over hierarchical | Rule: "one topic subdir level only, no deeper nesting." A flat concept namespace with cross-references, not a tree. |
| Write for yourself | Single-user by design. No collaboration surface at MVP. The user is the audience. |

If a wiki page violates any of these five rules, it is a **lint target** in our `lint` operation. That is not a post-hoc mapping — it is the design intent we can point to and defend.

## What Matuschak teaches beyond the principles

1. **"What matters is better thinking."** Not better note-taking. The evergreen notes practice exists to develop insight, not to produce archive material. This reframes llmwiki's value proposition: we are not a dumping ground for articles, we are a thinking assistant. Every feature must be judged on whether it helps the user think, not on whether it files something.

2. **Reading inbox / writing inbox.** Matuschak uses two inboxes — one for captured references, one for transient notes in flight. This is our `raw/subscriptions/` (reading inbox) + the "pending ingest" state on raw documents (writing inbox). Direct borrowing.

3. **Enormously indebted to Zettelkasten (Luhmann).** The evergreen notes practice is Matuschak's modernization of Niklas Luhmann's 1950s Zettelkasten method. The connection matters because Luhmann produced 90,000 notes and published 70 books from them — the method scales, empirically, to professional output over a lifetime. Our architecture must not impose limits that Luhmann wouldn't have tolerated.

4. **Associative ontologies.** Luhmann's Zettelkasten had no hierarchy — only numeric IDs and links between them. Matuschak extends this: links, not folders, are the organizing principle. Our wiki has topic folders (`concepts/`, `entities/`) for practical navigation, but the *semantic* organization is the link graph, and the lint pass enforces link density over folder depth.

## What this means for us

1. **Evergreen-ness is a lint rule.** The heuristic lint checks in the guardian agent include "orphan pages with no inbound links," "concepts frequently mentioned but lacking a dedicated page," "pages that mix multiple concepts" — one for each of Matuschak's five principles.

2. **The template check is not bureaucratic.** When the `write` tool rejects a page for missing a Sources line or for having body content without citations, it is enforcing atomicity and concept-orientation at the schema level. The rejection is the feature.

3. **Onboarding the user.** When a new user creates a workspace, the `guide()` output should include a short "what evergreen notes look like" primer so they know what to expect from the agent. The agent's output should feel like high-quality evergreen notes, not like summaries of sources.

4. **The "better thinking" framing.** When we write user-facing copy, the value is *thinking with the agent*, not *storing more things*. Marketing implication; also UX implication — the CLI's default verbs should be about questioning and compiling, not about uploading.
