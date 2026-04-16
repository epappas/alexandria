# Source: Antigravity.codes — "Karpathy's LLM Knowledge Bases: The Post-Code AI Workflow"
URL: https://antigravity.codes/blog/karpathy-llm-knowledge-bases
Fetched: 2026-04-15
Status: Fetched via WebFetch (summarized extraction)

---

# Karpathy's LLM Knowledge Bases: Post-Code AI Workflow

## Core Insight
Andrej Karpathy: **"A large fraction of my recent token throughput is going less into manipulating code, and more into manipulating knowledge."** Rather than generating software, he now compiles raw documents into structured markdown wikis that LLMs maintain autonomously.

## The 6-Step Workflow

1. **Data Ingest** — Source documents (articles, papers, repos, images) go into a `raw/` directory. Karpathy uses Obsidian Web Clipper to convert web content to markdown with locally downloaded images.
2. **LLM Compilation** — LLM transforms raw sources into a structured wiki with summaries, backlinks, categorized concepts, cross-references. *"The LLM writes and maintains all of the data of the wiki, I rarely touch it directly."*
3. **Scale** — His research wiki reached approximately 100 articles and 400,000 words.
4. **Querying** — LLM agent answers intricate research questions by following connections across articles.
5. **Multi-Format Output** — Results render as markdown files, Marp presentation slides, and Matplotlib visualizations — all viewed in Obsidian.
6. **Health Checks** — LLM-driven linting identifies inconsistencies, discovers missing data, reveals concept connections, and surfaces article candidates.

## Paradigm Shift
Beyond vibe coding — from prompter to **curator and questioner**, with LLMs handling organization and maintenance.

## Real-World Applications
- **Competitive Intelligence** — competitor sites, changelogs, filings
- **Literature Reviews** — 50–100 papers → findings and research gaps
- **Documentation** — living KB from README/ADR/postmortems
- **Product Research** — user feedback → prioritized insights
- **Personal Learning** — personalized curricula

## Key Community Responses
- Obsidian CEO Steph Ango emphasized **vault separation** — keep personal vaults distinct from agent-generated content.
- DAIR.AI's Elvis Saravia: data structure is foundational.

## Minimum Viable Setup
- Obsidian + Web Clipper
- Raw source directory structure
- Compilation prompt defining wiki generation rules
- Agentic IDE (Claude Code, Antigravity, etc.)
- Git version control

**Foundational principle:** Markdown as the universal interface — human-readable, LLM-native, version-controllable, tool-agnostic.
