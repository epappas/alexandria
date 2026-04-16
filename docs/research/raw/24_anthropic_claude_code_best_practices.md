# Source: Anthropic — "Claude Code Best Practices"

- **URL:** https://code.claude.com/docs/en/best-practices (redirected from https://www.anthropic.com/engineering/claude-code-best-practices)
- **Publisher:** Anthropic
- **Fetched:** 2026-04-15
- **Status:** Load-bearing direct quotes verbatim. The document is long; we extract the sections that justify the "agent as retriever" architecture.

---

## What Claude Code is (verbatim)

> "Claude Code is an agentic coding environment. Unlike a chatbot that answers questions and waits, Claude Code can read your files, run commands, make changes, and autonomously work through problems while you watch, redirect, or step away entirely."

## The fundamental constraint (verbatim)

> "Most best practices are based on one constraint: Claude's context window fills up fast, and performance degrades as it fills."

> "Claude's context window holds your entire conversation, including every message, every file Claude reads, and every command output."

> "LLM performance degrades as context fills. When the context window is getting full, Claude may start 'forgetting' earlier instructions or making more mistakes. The context window is the most important resource to manage."

**This is the core reason agentic retrieval works where naive RAG fails**: RAG stuffs top-k results into the context and prays; agentic retrieval lets the model decide what is worth the context cost.

## Let the agent fetch its own context (verbatim)

> "Let Claude fetch what it needs. Tell Claude to pull context itself using Bash commands, MCP tools, or by reading files."

This is the explicit Anthropic prescription for how retrieval should work: the agent pulls, the system does not push.

## The CLAUDE.md orientation pattern (verbatim)

> "CLAUDE.md is a special file that Claude reads at the start of every conversation. Include Bash commands, code style, and workflow rules. This gives Claude persistent context it can't infer from code alone."

> "Keep it concise. For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it. Bloated CLAUDE.md files cause Claude to ignore your actual instructions!"

This is the direct analogue of llmwiki's `SKILL.md` + `guide()` tool: a stable orientation document the agent reads at session start. And the warning is critical: orientation docs that grow unbounded stop being read. We enforce brevity in our SKILL.md for the same reason.

## Explore → plan → execute (verbatim)

> "Letting Claude jump straight to coding can produce code that solves the wrong problem. Use Plan Mode to separate exploration from execution."

The four-phase workflow: **Explore → Plan → Implement → Commit**. Applied to llmwiki query: **Explore (read overview, index, log) → Plan (decide which pages matter) → Synthesize (read + answer) → Log (append query to log.md if archived)**.

## Subagents for investigation (verbatim)

> "Since context is your fundamental constraint, subagents are one of the most powerful tools available. When Claude researches a codebase it reads lots of files, all of which consume your context. Subagents run in separate context windows and report back summaries."

> "The subagent explores the codebase, reads relevant files, and reports back with findings, all without cluttering your main conversation."

Subagents **are the answer** to "my agent read 50 files and now its context is poisoned." A subagent reads 50 files in its own window and returns 200 tokens of summary.

## Common failure patterns (verbatim)

> "**The infinite exploration.** You ask Claude to 'investigate' something without scoping it. Claude reads hundreds of files, filling the context. Fix: Scope investigations narrowly or use subagents so the exploration doesn't consume your main context."

## Why this matters for llmwiki

Claude Code is the working example of agentic retrieval over a filesystem. It reads, greps, lists, and follows its nose — with no embedding pipeline, no vector store, and no pre-chunked index. It works because:

1. **Primitives beat pipelines.** Read, Grep, Glob, Bash are composable primitives. An embedding search is not — it's a black box that returns top-k.
2. **Orientation docs (CLAUDE.md) + navigation primitives + subagents** is a complete retrieval system. That's the trio.
3. **Context management is the agent's job, and it's a hard problem.** The architecture should help the agent manage context: provide summaries at multiple levels (overview, index, per-topic summaries), support scoped reads (page ranges, sections), and expose subagent patterns.

Everything in Claude Code's best practices transfers directly to llmwiki with a literal rename: codebase → workspace, CLAUDE.md → SKILL.md, Read/Grep/Glob → our `read`/`search`/`list` tools. The patterns that work for code work for knowledge, and Anthropic has published the playbook.
