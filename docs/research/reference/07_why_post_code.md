# Reference: Why This Pattern — Post-Code AI Workflow

**Sources:** `raw/08_venturebeat_article.md`, `raw/11_antigravity_post_code.md`

Two framing pieces that don't add design details but do nail the *why*. Worth preserving because they sharpen our value proposition.

## The framing

Karpathy's own words: *"A large fraction of my recent token throughput is going less into manipulating code, and more into manipulating knowledge."*

The shift being named:
- **Code era:** LLM manipulates functions.
- **Knowledge era:** LLM manipulates facts, concepts, and their relationships.

The developer role flips from prompter to **curator + questioner**. The agent handles organization, maintenance, cross-references, and consistency.

## Community responses worth internalizing

1. **Steph Ango (Obsidian CEO) on vault separation.** Don't let an agent write into the same vault you keep your personal notes in. The agent's output is high-velocity and noisy; your personal notes are low-velocity and ground-truth. Cross-contamination corrodes trust.

   > *For us:* `~/.alexandria/` lives separately from `~/notes/` or `~/Obsidian/`. When we integrate with an existing Obsidian vault, we read-only mount it as a source, and write wiki pages into our own isolated workspace.

2. **Elvis Saravia (DAIR.AI).** Data structure is foundational — no amount of agent cleverness compensates for sloppy input.

   > *For us:* the `raw/` layer's schema is not optional. Every ingested source gets normalized metadata (URL, collected_at, published_at, topic) before the agent touches it.

## Use-case surface
The blogs list the real-world applications that actually land:
- Competitive intelligence (competitor sites, changelogs, filings).
- Literature reviews (50–100 papers → findings + gaps).
- Living docs from READMEs + ADRs + postmortems.
- Product research from user feedback, surveys, interviews.
- Personal curricula.

These become the user-facing templates we should pre-seed for new wikis. A new user shouldn't have to invent the schema themselves.
