# Source: MindStudio Blog — Karpathy LLM Wiki Knowledge Base with Claude Code
URL: https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code
Fetched: 2026-04-15
Status: Fetched via WebFetch

---

# Karpathy's LLM Wiki: Personal Knowledge Base with Claude Code

## Core Concept

Andrej Karpathy advocates organizing personal notes as structured markdown files queryable by LLMs rather than browsed manually. The system transforms "raw documents into a structured markdown knowledge base Claude can query."

## Key Architecture Components

**1. Markdown File Folder**
Your knowledge base contains research notes, meeting summaries, documentation, and reference material in plain text format.

**2. Consistent Internal Structure**
Each note includes:
- Title
- One-sentence summary
- Tags for topic identification
- Timestamps
- Main content section
- Related note links

**3. Claude Code Interface**
The terminal-based coding agent reads files directly from your local filesystem without requiring copy-paste operations.

## Why Markdown?

- **Portability**: Opens anywhere, no vendor lock-in
- **LLM Native**: Models recognize markdown syntax as structured information
- **Clarity**: Format encourages organized, focused notes
- **Future-Proof**: Plain text remains accessible indefinitely

## Five-Minute Setup (Obsidian Method)

**Step 1:** Install Obsidian, create vault folder (e.g., `~/wiki`)
**Step 2:** Create template at `_templates/note.md` with summary, tags, timestamps
**Step 3:** Organize into folders: projects, research, reference, meetings, inbox
**Step 4:** Migrate existing knowledge, start adding new notes
**Step 5:** Install Claude Code via Node.js: `npm install -g @anthropic-ai/claude-code`
**Step 6:** Query from terminal:
```
cd ~/wiki
claude
```

## Query Examples

- "What notes exist about machine learning interpretability?"
- "Summarize everything in research folder related to RAG systems"
- "Find vendor Acme Corp mentions and summarize key points"

## Optimization Practices

- Write summaries enabling quick relevance assessment
- Use consistent terminology across notes
- Link notes using `[[wiki links]]` format
- Keep individual notes focused rather than sprawling
- Use `/inbox` folder for unprocessed captures

## Scaling Consideration

Basic file-reading handles several hundred notes effectively. For larger wikis, add semantic search using tools like LlamaIndex to narrow candidates before full-file analysis.

## Distinction from Alternatives

Unlike Notion AI or ChatGPT, this approach keeps data in user-controlled files rather than proprietary systems, delivering more precise answers from personal knowledge rather than general web search.
