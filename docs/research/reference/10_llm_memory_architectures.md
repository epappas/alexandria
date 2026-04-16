# Reference: LLM Memory Architectures (MemGPT, Generative Agents)

**Sources:** `raw/18_memgpt.md`, `raw/19_generative_agents.md`

Two papers about LLMs with persistent memory. They are close cousins to alexandria — close enough that we should know exactly why we are not them.

## MemGPT (Packer et al. 2023, UC Berkeley)

**The move:** treat the LLM context window like CPU RAM and the external store like disk. The model calls memory-management functions (load, swap, evict) against a two-tier memory. Interrupts transfer control when the model needs to page data in.

Abstract quote:

> "we propose virtual context management, a technique drawing inspiration from hierarchical memory systems in traditional operating systems that provide the appearance of large memory resources through data movement between fast and slow memory."

**Why it matters to us:** MemGPT's core insight is that **the model should manage its own memory explicitly**. Tools for loading, writing, and editing memory are first-class. The model is not a passive consumer of retrieved context — it actively manages what lives in its working set.

**What alexandria borrows:**
- The guardian agent's tool surface (`guide`, `read`, `search`, `write`, `history`) is literally MemGPT's memory-management function set, specialized for a markdown knowledge base.
- The `history()` tool — structured query over `wiki_log_entries` — plays the role MemGPT's memory functions play for conversation history.
- The agent's `guide()` call at session start is the MemGPT "initial swap-in" — load the directory index, recent log, and current state into the working context.

**What alexandria does differently:**
- MemGPT's slow memory is opaque (a structured buffer the model reads/writes through functions). alexandria's slow memory is **human-readable markdown** the user can open in Obsidian, version in git, and edit directly. The transparency is the product.
- MemGPT optimizes for long **conversations**. alexandria optimizes for long **bodies of knowledge**. Different workloads, different retrieval patterns.
- MemGPT has no schema for its external store. alexandria enforces one (`SKILL.md`) and validates every write against it.

## Generative Agents (Park et al. 2023, Stanford)

**The move:** each agent has a memory stream (append-only natural-language record of experiences), a reflection mechanism (periodic synthesis of lower-level observations into higher-level insights), and a retrieval function that scores memories by **recency + importance + relevance**.

**Why it matters to us:** this paper is the closest prior work to alexandria's self-awareness story. Generative Agents show that a long natural-language log plus periodic synthesis plus a scored retrieval function is enough to produce plausible continuity over thousands of events.

**What alexandria borrows:**

| Generative Agents | alexandria |
|---|---|
| Memory stream | `wiki/log.md` + `wiki_log_entries` table |
| Reflection | The lint pass + cascade updates during ingest |
| Recency scoring | `wiki_log_entries.created_at` index |
| Importance scoring | Mandatory `overview.md` (user-designated "key findings") |
| Relevance scoring | FTS5 full-text search over documents |

The guardian's self-awareness block — *"what did I write in the last N days, which pages did I touch, which ingests left cascade updates pending"* — is exactly Park et al.'s retrieval function restated for a knowledge base instead of a social simulacrum.

**What alexandria does differently:**
- Generative Agents generate their own memories (observations of a simulated world). alexandria's memories are **the user's sources** + **the agent's own writes**. The agent does not hallucinate observations.
- The reflection step runs **on demand** (lint) and **as part of ingest** (cascade updates), not on a timer. Trust considerations: automatic reflections would drift without human supervision.
- Importance is **user-declared** via the `overview.md` "Key Findings" section, not machine-scored. We refuse to automate the value judgment.

## What the two papers tell us we got right

1. **Memory management belongs to the model.** Both MemGPT and Generative Agents argue that the LLM must actively curate its own memory. Our guardian does exactly this — it decides what to read, what to write, what to cascade-update.
2. **Structured access beats chunk retrieval.** Both papers beat vanilla RAG by adding structure (pages in MemGPT, reflections in GA). Our markdown wiki is the same idea at a different granularity.
3. **Self-awareness is tractable.** Neither paper needs a separate "memory layer" — the log plus the data is enough. We bet on the same thing: `wiki/log.md` + `wiki_log_entries` + the wiki pages themselves comprise the agent's memory, with no separate component.

## What we explicitly reject

1. **Reflection without supervision** (Generative Agents). The agent generating new summaries on a timer is a hallucination factory when the "world" is the user's research. We gate reflection behind explicit ingest/lint calls.
2. **Opaque paging** (MemGPT). We refuse to have a store the user cannot read. Every page is a markdown file they can open in a text editor.
3. **Recency as the dominant signal.** For knowledge bases, recency is a weak signal compared to citation graph and cross-references. `wiki_log_entries` sorts by time for display; the agent's actual retrieval goes through FTS5 and the citation graph.

## The sharpened claim

alexandria is **Generative Agents' memory architecture applied to personal research, with MemGPT's tool-based self-management, and the user as the arbiter of importance**. We keep the ideas the literature has validated and refuse the parts that require automated judgment the user has not authorized.
