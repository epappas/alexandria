# alexandria

Local-first single-user knowledge engine. Accumulates your gathered knowledge
and exposes it via MCP to connected agents like Claude Code for retroactive
query, retrieval, and review.

## Quick start

```bash
pip install alexandria        # or: pip install -e ".[dev]"
alexandria init               # creates ~/.alexandria/
alexandria status             # verify the install
alexandria mcp install claude-code  # register with Claude Code (Phase 1)
```

## Status

Phase 0 — foundation. See `docs/IMPLEMENTATION_PLAN.md` for the full 13-phase
roadmap and `docs/architecture/` for the 20 architecture documents.

## License

MIT
