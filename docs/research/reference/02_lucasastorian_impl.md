# Reference: lucasastorian/alexandria — Reference Python Implementation

**Sources:** `raw/04_lucasastorian_alexandria_repo.md`, `raw/12_lucasastorian_full_service_tour.md`
**Local clone:** `/tmp/alexandria-lucas`

This is the closest production-ready reference to what we're building. It is a multi-tenant SaaS at alexandria.app plus a self-hostable stack. About one-third Python (API + MCP server), two-thirds TypeScript (Next.js UI). Apache 2.0.

## Architecture at a glance
- **Web** (Next.js 16) — dashboard, document viewer, wiki renderer.
- **API** (FastAPI + asyncpg + aioboto3) — auth, uploads (TUS protocol), OCR orchestration, CRUD.
- **Converter** (FastAPI + LibreOffice, isolated) — office-to-PDF, non-root, no AWS creds.
- **MCP Server** (FastMCP + Supabase OAuth) — the agent surface. Exposes `guide`, `search`, `read`, `write`, `delete`.
- **Database** — Supabase Postgres with RLS + PGroonga for full-text search.
- **Storage** — S3-compatible for raw binary uploads and extracted images.

## Multi-tenant model (the bit we care about most)
- Every row is owned by a Supabase Auth user via `user_id UUID REFERENCES users(id)`.
- RLS policies pin reads to `auth.uid()`. The MCP server sets `request.jwt.claims` inside a Postgres transaction before every read (see `mcp/db.py::_set_rls`).
- Writes go through the service role but explicitly `WHERE user_id = $1` — no RLS-only writes.
- Users can own many `knowledge_bases` (per-user `(slug, name)` unique). A KB is the unit the agent works within.

## The virtual-filesystem trick
There is no real filesystem. The `documents` table stores both raw sources and wiki pages, distinguished by the `path` column:
- `path = '/'` + `filename = 'paper.pdf'` → a raw source.
- `path = '/wiki/concepts/'` + `filename = 'attention.md'` → a wiki page.

This means glob patterns like `/wiki/**`, `*.md`, `/wiki/concepts/*` are implemented as SQL `LIKE` + `fnmatch`. Big upside: one query surface, uniform ACL. Downside: you can't `ls` the disk.

## MCP tools — the agent's contract surface
Registered in `mcp/tools/__init__.py`. Every tool takes `knowledge_base` as its first argument so the agent is always scoped.

- **guide** — Onboarding. Returns a long prompt (see `mcp/tools/guide.py::GUIDE_TEXT`) that teaches the wiki schema (Overview / Concepts / Entities / Log) and appends the user's KB list. Claude is instructed to call this first.
- **search** — Two modes: `list` (glob browse) and `search` (PGroonga keyword over `document_chunks` with scoring, page numbers, and header breadcrumbs). Supports path scoping (`/wiki/**`) and tag filtering.
- **read** — Single file, page range (`pages="1-50"`), section filter, optional embedded images, OR glob batch read with a 120k-char budget that samples across many files. The system prompt pushes Claude to use batch reads aggressively.
- **write** — `create` / `str_replace` / `append`. Create requires title + tags. `str_replace` errors on multi-match (forces reading first). Supports SVG + CSV assets so the agent can build diagrams and embed them.
- **delete** — Exact or glob. Soft-delete (`archived = true`). Protected files: `/wiki/overview.md` and `/wiki/log.md` cannot be deleted. Unqualified `*`/`**`/`**/*` are refused.

## The guide prompt — operational schema
The schema taught to the agent is opinionated:
- `/wiki/overview.md` — mandatory hub page, updated on EVERY ingest with source count, key findings, recent updates.
- `/wiki/concepts/` — abstract ideas.
- `/wiki/entities/` — concrete things (people, products, papers).
- `/wiki/log.md` — append-only, parseable headers.
- Optional `/wiki/comparisons/`, `/wiki/timeline.md`.
- **Every page must have at least one visual** (mermaid, table, or SVG asset).
- **Every factual claim must cite a source** via markdown footnote `[^1]: paper.pdf, p.3`.
- Parent/child page hierarchy via paths.

## Key engineering patterns to copy
- **`ScopedDB`** — a thin wrapper that holds an acquired connection with RLS set. Injected via FastAPI `Depends(get_scoped_db)`. Clean boundary.
- **Startup recovery** — `_recover_stuck_documents` re-schedules any `pending/processing` docs on API startup, so crashes don't leave orphans.
- **Token verifier** — `SupabaseTokenVerifier` validates JWTs against Supabase JWKS with `audience='authenticated'`; returns an `AccessToken` whose `client_id` is the `sub` claim.
- **Bootstrapped structural pages** — on KB creation, two documents are inserted: `/wiki/overview.md` and `/wiki/log.md`, with templated starter content. The wiki is never "empty."
- **Chunker + PGroonga** — instead of vector embeddings, chunks are indexed with PGroonga for keyword search with scoring. Practical tradeoff: skips the embedding service entirely and still supports multi-language.

## What's missing for our use case
- Only supports uploaded files. No pluggable sources (Notion, Obsidian, S3, git, GCS). Every source is a blob that went through `POST /upload`.
- Wiki pages live in the same table as sources. There's no per-source-type adapter interface.
- The whole stack is Supabase-coupled. Porting to generic Postgres + our own auth requires rewriting `auth.py`, RLS policies, and OAuth wiring.
- No notion of a scheduled "sync" from an external source.

## Files worth re-reading when we start coding
- `mcp/server.py` — FastMCP wiring with OAuth + transport security.
- `mcp/db.py::_set_rls` — the RLS-per-transaction pattern.
- `mcp/tools/guide.py::GUIDE_TEXT` — the operational system prompt taught to Claude.
- `mcp/tools/write.py` — `str_replace` semantics (exactly-one-match or error).
- `api/routes/knowledge_bases.py` — KB create seeds overview + log.
- `supabase/migrations/001_initial.sql` — table shapes and RLS policies.
