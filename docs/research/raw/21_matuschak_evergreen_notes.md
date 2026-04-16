# Source: Andy Matuschak — "Evergreen notes"

- **URL:** https://notes.andymatuschak.org/Evergreen_notes
- **Author:** Andy Matuschak (personal public notes)
- **Fetched:** 2026-04-15
- **Status:** Definition + five core principles retrieved. The note is itself densely linked — each principle has its own note at a separate URL.

---

## Definition (extracted)

> Evergreen notes are written and organized to **evolve, contribute, and accumulate over time, across projects**.

They differ from transient notes in that the goal is "effectively developing insight" rather than note-taking per se.

## Five core principles

1. **Evergreen notes should be atomic.**
2. **Evergreen notes should be concept-oriented.**
3. **Evergreen notes should be densely linked.**
4. **Prefer associative ontologies to hierarchical taxonomies.**
5. **Write notes for yourself by default, disregarding audience.**

## Why they work (paraphrased from the note)

The point is "better thinking," not better note-taking. Evergreen notes accumulate value because each note is atomic (reusable in many contexts), concept-oriented (named after the idea, not the source), densely linked (the graph is the substrate), and associatively organized (flat namespace with connections, not hierarchies).

The practice is, in Matuschak's words, "enormously indebted" to Niklas Luhmann's Zettelkasten method.

## Implementation artifacts mentioned

- Reading inbox (capture of references)
- Writing inbox (transient notes in flight)
- Executable strategy for writing (daily / weekly process)
- Taxonomy of note types (evergreen, literature, etc.)

## Why this matters for alexandria

The wiki pages alexandria builds need to satisfy all five principles *automatically*. The guardian agent must:

1. Write **atomic** pages — one concept per page, not "everything I learned from this source."
2. Name pages after the **concept**, not the source file.
3. **Link densely** during ingest — cascade updates exist precisely to maintain link density.
4. Place pages in a flat `concepts/` + `entities/` namespace rather than deep taxonomies. We already enforce "one topic level only."
5. Write for the user first — the agent is the user's assistant, not a publisher.

The correspondence is exact enough that `evergreen-ness` can be a lint check: a page that violates any of these principles is a lint target.
