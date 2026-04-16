# llmwiki

Local-first single-user knowledge engine. Accumulates your gathered knowledge
and exposes it via MCP to connected agents like Claude Code for retroactive
query, retrieval, and review.

## Quick start

```bash
pip install llmwiki        # or: pip install -e ".[dev]"
llmwiki init               # creates ~/.llmwiki/
llmwiki status             # verify the install
llmwiki mcp install claude-code  # register with Claude Code (Phase 1)
```

## Status

Phase 0 — foundation. See `docs/IMPLEMENTATION_PLAN.md` for the full 13-phase
roadmap and `docs/architecture/` for the 20 architecture documents.

## License

MIT
