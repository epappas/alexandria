# Source: lucasastorian/alexandria — Full Service Tour (cloned repo)
URL: https://github.com/lucasastorian/alexandria
Local clone: /tmp/alexandria-lucas
Fetched: 2026-04-15

This is the most relevant reference implementation for our Python service. It is a FastAPI + MCP + Supabase app that multi-tenants wikis and exposes them to Claude via MCP.

---

## Architecture (from README)

```
Next.js Frontend  →  FastAPI Backend  →  Supabase (Postgres)
                           │
                     MCP Server  ←──  Claude (via MCP connector)
```

| Component | Stack | Responsibilities |
|---|---|---|
| Web (`web/`) | Next.js 16, React 19, Tailwind, Radix UI | Dashboard, PDF/HTML viewer, wiki renderer, onboarding |
| API (`api/`) | FastAPI, asyncpg, aioboto3 | Auth, uploads (TUS), document processing, OCR (Mistral) |
| Converter (`converter/`) | FastAPI, LibreOffice | Isolated office-to-PDF (non-root, zero AWS creds) |
| MCP (`mcp/`) | MCP SDK, Supabase OAuth | Tools for Claude: `guide`, `search`, `read`, `write`, `delete` |
| Database | Supabase (Postgres + RLS + PGroonga) | Documents, chunks, KBs, users |
| Storage | S3-compatible | Raw uploads, tagged HTML, extracted images |

## Multi-tenancy model
- Every row belongs to a `user_id` referencing Supabase Auth.
- Row-level security enforced via Postgres RLS policies (`user_id = auth.uid()`).
- The MCP and API layers run queries inside a `ScopedDB` transaction that SETs `request.jwt.claims.sub` before reading. Writes go through the service role explicitly scoped by `user_id`.
- `knowledge_bases` are per-user, identified by `(user_id, slug)`. A user can own many KBs.

## SQL schema (excerpts)

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    onboarded BOOLEAN NOT NULL DEFAULT false,
    page_limit INTEGER NOT NULL DEFAULT 500,
    storage_limit_bytes BIGINT NOT NULL DEFAULT 1073741824,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TABLE knowledge_bases (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    UNIQUE(user_id, slug),
    UNIQUE(user_id, name)
);

CREATE TABLE documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    title TEXT,
    path TEXT DEFAULT '/' NOT NULL,        -- virtual filesystem: '/' for sources, '/wiki/...' for wiki pages
    file_type TEXT NOT NULL,
    file_size BIGINT DEFAULT 0 NOT NULL,
    status document_status DEFAULT 'pending' NOT NULL,
    page_count INTEGER CHECK (page_count IS NULL OR page_count <= 300),
    content TEXT,
    tags TEXT[] DEFAULT '{}' NOT NULL,
    metadata JSONB,
    version INTEGER DEFAULT 0 NOT NULL,
    archived BOOLEAN DEFAULT false NOT NULL,
    ...
);

CREATE TABLE document_pages (...page-level content for PDFs, spreadsheets, etc...);
CREATE TABLE document_chunks (...chunked content indexed with PGroonga for keyword search...);

CREATE EXTENSION IF NOT EXISTS pgroonga;
CREATE INDEX idx_chunks_content_pgroonga ON document_chunks USING pgroonga (content);
```

Key insight: **there is no filesystem**. Both raw sources and wiki pages are rows in the `documents` table with a virtual path:
- `/foo.pdf` → a raw source
- `/wiki/concepts/attention.md` → a wiki page

## MCP tools exposed to Claude

Registered in `mcp/tools/__init__.py`:

1. **guide** — Onboarding tool. Returns a long `GUIDE_TEXT` that teaches Claude the wiki schema (Overview, Concepts, Entities, Log categories) plus a live list of the user's KBs and their counts. Call first.
2. **search** — Modes: `list` (glob-browse) and `search` (PGroonga keyword search over `document_chunks` with scoring). Supports path scoping (`/wiki/**`, `*.pdf`) and tag filtering. Results include deep-links back to the web UI.
3. **read** — Single file, page ranges (`pages="1-50"`), section filters, optional embedded images, or glob batch read (`*.md`, `/wiki/**`) up to a 120k char budget. Prefers batch reads to minimize round trips.
4. **write** — Commands: `create` (new note/asset, requires title + tags), `str_replace` (exact-match edit, errors on multi-match), `append`. Supports SVG/CSV asset files embedded in wiki pages.
5. **delete** — Glob or exact path. Archives (soft-delete) by setting `archived = true`. Refuses to delete `/wiki/overview.md` and `/wiki/log.md` (structural pages). Refuses unqualified `*`, `**`, `**/*`.

## The `guide` prompt — wiki schema taught to the agent

The LLM is instructed to maintain:
- `/wiki/overview.md` — mandatory hub page: scope, source count, key findings, recent updates. Updated on **every** ingest.
- `/wiki/concepts/` — abstract ideas (scaling laws, attention, etc.)
- `/wiki/entities/` — concrete things (Transformer, OpenAI, specific papers)
- `/wiki/log.md` — append-only chronological log with parseable headers `## [YYYY-MM-DD] ingest | Source Title`
- Optional pages: `/wiki/comparisons/`, `/wiki/timeline.md`

**Mandatory requirements** on every wiki page:
- At least one visual (mermaid, table, or SVG asset).
- Every factual claim cites source via markdown footnote: `[^1]: paper.pdf, p.3` (full filename, page numbers for PDFs).
- Parent/child hierarchy via paths — `/wiki/concepts.md` parent summarizes, children go deep.

## Core workflows (from guide.py)

### Ingest
1. `read(path="source.pdf", pages="1-10")`
2. Discuss takeaways with user
3. Create/update concept pages in `/wiki/concepts/`
4. Create/update entity pages in `/wiki/entities/`
5. Update `/wiki/overview.md` (source count, key findings, recent updates)
6. Append entry to `/wiki/log.md`
7. *A single source typically touches 5–15 wiki pages.*

### Answer a question
1. `search(mode="search", query="term")`
2. Read relevant pages and sources
3. Synthesize with citations
4. If answer is valuable, file it as a new wiki page
5. Append a query entry to `/wiki/log.md`

### Lint
- Check contradictions, orphan pages, missing cross-references, stale claims, undocumented concepts.
- Append a lint entry to `/wiki/log.md`.

## Auth flow
- MCP server uses `SupabaseTokenVerifier` that validates JWTs against Supabase JWKS, audience `authenticated`. The `sub` claim becomes the `user_id` used by all scoped queries.
- MCP config: user copies an MCP URL from the dashboard and adds it as a Claude connector; Claude handles the OAuth dance through Supabase.

## KB creation seeds two structural pages
From `api/routes/knowledge_bases.py`:
- `/wiki/overview.md` with a templated scope paragraph + "Key Findings: no sources yet" + "Recent Updates: none".
- `/wiki/log.md` with an initial `## [YYYY-MM-DD] created | Wiki Created` entry.

## Key implementation details worth copying
- **Chunker + PGroonga** for keyword search on Japanese/English content (`document_chunks` with 10k-char cap, `token_count`, `header_breadcrumb`).
- **TUS** protocol for resumable uploads.
- **Mistral OCR** for PDF extraction into `document_pages` (one row per page, content ≤ 500k chars).
- **Isolated converter service** (LibreOffice) with zero AWS creds — defense in depth.
- **Recovery on startup**: `_recover_stuck_documents` re-schedules any docs in `pending/processing` after a crash.
- **Service-role writes** — reads go through RLS + scoped connection; writes use the service role but pin `WHERE user_id = $1` explicitly.

## Files worth re-reading for implementation
- `api/main.py`, `api/scoped_db.py`, `api/deps.py`
- `api/routes/knowledge_bases.py`, `api/routes/documents.py`
- `api/services/chunker.py`, `api/services/ocr.py`, `api/services/s3.py`
- `api/infra/tus.py`
- `mcp/server.py`, `mcp/auth.py`, `mcp/db.py`
- `mcp/tools/{guide,search,read,write,delete,helpers}.py`
- `supabase/migrations/001_initial.sql`
