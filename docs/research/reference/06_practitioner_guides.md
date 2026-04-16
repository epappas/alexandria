# Reference: Practitioner Guides (MindStudio, Starmorph, DAIR.AI)

**Sources:** `raw/02_mindstudio_blog.md`, `raw/09_dair_academy.md`, `raw/10_starmorph_guide.md`

These three articles cover the same ground (Karpathy's pattern, the three layers, ingest/query/lint) at tutorial depth. For our design, the only distinctive nuggets:

## Non-obvious nuggets

1. **Obsidian vault layout that actually works in practice** (MindStudio):
   ```
   ~/wiki/
     _templates/note.md    # consistent note schema
     projects/
     research/
     reference/
     meetings/
     inbox/                # unprocessed capture buffer
   ```
   The `inbox/` pattern is the practitioner's answer to "where does a new note go before I know where it belongs?"

2. **QMD (Starmorph)** — a small tool that adds BM25 + vector + LLM re-ranking to a markdown directory. Shows that hybrid search over markdown is a solved problem we can plug in later.

3. **Scale cliff at ~200 notes** (MindStudio). Plain file-reading works up to several hundred notes. Beyond that, you need semantic narrowing before the LLM reads full files. Confirms lucasastorian's PGroonga choice is not premature optimization.

4. **"LLM Wiki is a traceable Graph RAG"** (Starmorph). Reframes the pattern as manually-maintained Graph RAG, which is a useful mental model when explaining it to RAG-literate engineers.

5. **Template convention** (MindStudio) — note fields: title, one-sentence summary, tags, timestamps, body, related-note links. Matches Astro-Han's `article-template.md` almost exactly; confirms this is the settled convention.

## What this means for us
Three things we should bake into the MVP, straight from practitioner experience:
- Ship an `inbox/` equivalent — a landing zone for sources the agent hasn't yet classified.
- The "scale cliff at ~200 notes" data point does NOT justify adding a vector store. We commit to agentic navigation (see `12_agentic_retrieval.md`); the fix for large workspaces is sharper orientation documents, topic-level summary pages produced by the lint pass, and subagent patterns — the same approach Claude Code uses for codebases of any size.
- Enforce the note template at write-time, not just in the prompt. Reject writes that don't include the required frontmatter.

Note on the earlier version of this doc: a previous draft recommended "PGroonga today, hybrid PGroonga + pgvector + LLM re-rank later." That recommendation has been superseded by the agentic-retrieval commitment. We do not scaffold a vector fallback.
