# Source: Anthropic — "Building Effective Agents"

- **URL:** https://www.anthropic.com/engineering/building-effective-agents
- **Publisher:** Anthropic (engineering blog)
- **Fetched:** 2026-04-15
- **Status:** Key definitions + quotes verbatim.

---

## Workflows vs agents — the distinction (verbatim)

> "Workflows: systems where LLMs and tools are orchestrated through predefined code paths."

> "Agents: systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks."

The fundamental difference is control flow — workflows follow predetermined paths, agents make real-time decisions about execution.

## The agent loop (verbatim)

> "[Agents are] typically just LLMs using tools based on environmental feedback in a loop."

> "it's crucial for the agents to gain 'ground truth' from the environment at each step (such as tool call results or code execution) to assess its progress."

The core pattern: the model receives tool results, evaluates progress, determines next actions iteratively until task completion.

## The augmented LLM building block (verbatim)

> "an LLM enhanced with augmentations such as retrieval, tools, and memory"

These models can "actively use these capabilities — generating their own search queries, selecting appropriate tools, and determining what information to retain."

## Why this matters for alexandria

Anthropic's definition makes "retrieval via agent tool use" first-class. The agent *generates its own search queries*, *selects appropriate tools*, and *determines what information to retain*. That is not a pipeline running before the model — it is the model itself, running in a loop. Exactly the pattern alexandria must adopt: the guardian is the retrieval algorithm, and our job is to give it good primitives.
