# Source: Packer et al. — "MemGPT: Towards LLMs as Operating Systems"

- **arXiv:** 2310.08560
- **URL:** https://arxiv.org/abs/2310.08560
- **Authors:** Charles Packer, Sarah Wooders, Kevin Lin, Vivian Fang, Shishir G. Patil, Ion Stoica, Joseph E. Gonzalez (UC Berkeley)
- **Submitted:** 2023-10-12; revised 2024-02-12
- **Fetched:** 2026-04-15
- **Status:** Abstract verbatim + key contributions.

---

## Abstract (verbatim)

> "Large language models (LLMs) have revolutionized AI, but are constrained by limited context windows, hindering their utility in tasks like extended conversations and document analysis. To enable using context beyond limited context windows, we propose virtual context management, a technique drawing inspiration from hierarchical memory systems in traditional operating systems that provide the appearance of large memory resources through data movement between fast and slow memory. Using this technique, we introduce MemGPT (Memory-GPT), a system that intelligently manages different memory tiers in order to effectively provide extended context within the LLM's limited context window, and utilizes interrupts to manage control flow between itself and the user."

## Technical contributions

1. **Virtual context management** — OS paging metaphor applied to LLM context windows. Data moves between "fast" (in-context) and "slow" (external) memory.
2. **Dual-tier memory architecture** — main context vs external context, analogous to CPU cache vs disk.
3. **LLM-callable memory functions** — the model invokes operations to retrieve, write, and edit its own memory; interrupt-driven control flow.
4. **Evaluation domains** — document analysis beyond native context limits; multi-session chat with persistent memory, reflection, and dynamic evolution.
