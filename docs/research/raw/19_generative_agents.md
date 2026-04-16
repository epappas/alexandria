# Source: Park et al. — "Generative Agents: Interactive Simulacra of Human Behavior"

- **arXiv:** 2304.03442
- **URL:** https://arxiv.org/abs/2304.03442
- **Authors:** Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein (Stanford / Google)
- **Submitted:** 2023-04-07 (v1); revised 2023-08-06 (v2)
- **Category:** CS > HCI
- **Fetched:** 2026-04-15
- **Status:** Abstract quote + architecture summary.

---

## Abstract (verbatim opening)

> "Believable proxies of human behavior can empower interactive applications ranging from immersive environments to rehearsal spaces for interpersonal communication to prototyping tools."

The researchers introduce computational agents that simulate realistic daily activities and social interactions, demonstrated in a Sims-inspired sandbox with 25 agents capable of autonomous coordination (e.g., organizing a Valentine's Day party).

## Technical architecture

1. **Memory stream** — agents maintain a complete record of experiences in natural language, observations and interactions recorded chronologically.
2. **Reflection mechanism** — the system synthesizes accumulated memories into higher-level reflections, enabling agents to develop coherent perspectives and plan behavior based on past experiences.
3. **Retrieval function** — weighted combination of three signals:
   - **recency** (prioritize recent events)
   - **importance** (significance assessment)
   - **relevance** (contextual connection to current planning)

The paper argues that observation, planning, and reflection are each individually necessary for generating believable behavior.
