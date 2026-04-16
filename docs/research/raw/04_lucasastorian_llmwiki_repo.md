# Source: lucasastorian/alexandria (GitHub repo)
URL: https://github.com/lucasastorian/alexandria
Fetched: 2026-04-15
Status: Fetched via WebFetch (README-level extraction)

---

# LLM Wiki Repository Summary

## Overview
LLM Wiki is an open-source implementation of Karpathy's LLM Wiki concept, enabling users to upload documents and use Claude via MCP to automatically compile and maintain a knowledge base.

## Core Concept
The system operates on three layers:
- **Raw Sources**: Immutable PDFs, articles, notes, and transcripts
- **The Wiki**: LLM-generated markdown pages with summaries and cross-references
- **The Tools**: Search, read, and write capabilities through MCP

## Top-Level Directory Structure
```
.github/workflows/
api/
converter/
mcp/
supabase/migrations/
tests/
web/
.env.example
.gitignore
LICENSE
README.md
docker-compose.test.yml
docker-compose.yml
netlify.toml
pytest.ini
wiki-page.png
```

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web | Next.js 16, React 19, Tailwind, Radix UI | Dashboard and wiki renderer |
| API | FastAPI, asyncpg, aioboto3 | Authentication and document processing |
| Converter | FastAPI, LibreOffice | Office-to-PDF conversion |
| MCP | MCP SDK, Supabase OAuth | Claude integration tools |
| Database | Supabase (Postgres + RLS + PGroonga) | Data persistence |
| Storage | S3-compatible | File management |

## MCP Tools Available to Claude
- **guide**: Explains wiki functionality
- **search**: Keyword search with PGroonga ranking
- **read**: Access documents with page ranges and images
- **write**: Create/edit wiki pages with assets
- **delete**: Archive documents by pattern

## Core Operations
**Ingest**: Sources trigger automatic wiki updates across multiple related pages with consistency checks.
**Query**: Users ask complex questions; answers synthesize existing knowledge rather than re-deriving from chunks.
**Lint**: Health checks identify inconsistencies, stale claims, orphaned pages, and missing references.

## Self-Hosting Setup (Abbreviated)
```bash
psql $DATABASE_URL -f supabase/migrations/001_initial.sql
cd api && uvicorn main:app --reload        # port 8000
cd mcp && uvicorn server:app --reload      # port 8080
cd web && npm run dev                       # port 3000
```

## Key Environment Variables
- `DATABASE_URL`: PostgreSQL connection
- `SUPABASE_URL`, `SUPABASE_JWT_SECRET`: Database service
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`: Storage
- `MISTRAL_API_KEY`: PDF OCR capability
- `APP_URL`, `CONVERTER_URL`: Service URLs

## Language Composition
- TypeScript: 61.9%
- Python: 32.3%
- PL/pgSQL: 3.2%
- CSS: 2.3%

## License
Apache 2.0

## Key Insight
The project addresses knowledge base maintenance burden by automating cross-reference updates and consistency checks — tasks humans typically abandon due to scaling complexity.
