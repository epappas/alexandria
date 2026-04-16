# 05 — Sources, Sync, and Subscriptions

> **Cites:** `research/reference/04_atomicmemory_compiler.md`, `research/reference/06_practitioner_guides.md`, `research/reference/07_why_post_code.md`

A workspace's raw layer is a **union over pluggable adapters**. Local files, code, papers, GitHub repos, gists, Drive, S3, Notion, newsletters, Twitter feeds — every one of them lands as files under `raw/<adapter>/...` and rows in SQLite, so the agent sees one uniform interface.

## One interface, many adapters

```python
class SourceAdapter(Protocol):
    type: ClassVar[str]             # "local" | "notion" | "github" | ...
    kind: ClassVar[AdapterKind]     # SOURCE | SUBSCRIPTION | STORAGE

    async def validate(self, config: dict) -> None: ...
    async def list(self, config: dict, since: datetime | None) -> AsyncIterator[SourceItem]: ...
    async def fetch(self, config: dict, item: SourceItem) -> FetchedDocument: ...

    # Optional — only for storage-kind adapters that can write too
    async def push(self, config: dict, doc: LocalDocument) -> None: ...

    # Optional — only for subscription-kind adapters that support webhooks
    def webhook_handler(self) -> Callable | None: ...
```

Four adapter **kinds**, same interface:

- **SOURCE** — one-shot or polled import (papers on disk, a Notion database, a git repo). Stored as files under `raw/`.
- **SUBSCRIPTION** — continuous polling for new *documents* (blogs, Substack, YouTube, newsletters via IMAP). Stored as files under `raw/subscriptions/`. See `09_subscriptions_and_feeds.md`.
- **EVENT_STREAM** — continuous ingestion of fine-grained activity events (GitHub commits / issues / PRs, Calendar meetings, Gmail threads, Slack / Discord messages, cloud-storage changes, and **conversation transcripts from Claude Code / Cursor / Codex / ChatGPT**). Stored as **structured rows in SQLite**, not as files — the volume and shape make filesystem storage wrong. See `10_event_streams.md` for the general design and `12_conversation_capture.md` for the conversation-specific hybrid (which lands BOTH as a markdown document in `raw/conversations/` AND as structured turn/tool-call events — same adapter, both layers).
- **STORAGE** — bidirectional: imports as a source AND accepts `push()` calls to write wiki exports back (Google Drive, S3, GCS, Dropbox).

One class can implement multiple kinds. Notion, for instance, is both a SOURCE (pages as raw material) and potentially a STORAGE (publish wiki exports back to a Notion database).

## Adapters we ship at MVP

### Local sources

#### `local` — filesystem directory
Config: absolute path, optional glob, optional extensions filter.
List walks the tree, returns files + mtimes. Fetch reads content or tags PDFs for extraction.

#### `obsidian` — Obsidian vault (read-only)
Config: vault path.
Markdown-specific: strips `[[wikilinks]]` to text, preserves frontmatter, follows aliases. **We never write into the vault.**

#### `clipboard` / `paste` — one-shot captures
The CLI offers `alexandria paste --workspace X --title "..."` to drop something from stdin into `raw/local/`. A subscription-adjacent flow for things without a real source.

### Code sources

#### `github-repo`
Config: repo URL, branch, optional subdirectory, optional auth token (GitHub PAT or app install).
Clones on first run, fetches on subsequent. Respects `.gitignore`. Filters by language/extension (opt-in). Treats `docs/`, `README*`, `CHANGELOG*`, `.md` files as primary source material. Optionally ingests code as a secondary source (useful for "what does this repo do?" queries).
Webhook: GitHub push events.

#### `gist`
Config: gist URL or user+gist ID, optional auth.
Pulls gist files as raw markdown/code. Polls for revision changes.

#### `local-repo`
Config: local git repo path, branch.
Same as `github-repo` but reads from disk. For the user's own projects.

### Document sources

#### `papers` / `arxiv`
Config: arxiv IDs, DOIs, or a local folder of PDFs.
For arxiv: fetches PDF + metadata via the arxiv API. For local: uses the `local` adapter with PDF extraction (pymupdf or pdfplumber).

#### `url` — one-off web article
Config: URL.
Runs in the sync worker with an allowlisted HTTP client. Converts HTML to markdown (readability + markdownify). Saves the original HTML alongside for provenance.

### Knowledge platforms

#### `notion`
Config: integration token + database IDs or page IDs.
Lists pages via the Notion API, converts blocks to markdown via a deterministic mapping. Polls every N minutes.

#### `confluence`, `roam`, `logseq` — post-MVP
Same shape as Notion: read-only, poll-based, block-to-markdown.

### Cloud storage (bidirectional)

#### `s3`, `gcs`
Config: bucket, prefix, credentials.
- **Source mode** — recurses the prefix; objects beneath it become raw items.
- **Storage mode** — accepts `push()` calls that upload exported wiki pages (user opt-in via `alexandria export --to s3://...`).
- Never writes to the bucket unless explicitly in storage mode.

#### `google-drive`, `dropbox`
Same shape as S3 — OAuth-based, folder-scoped, bidirectional if the user opts in.

### Subscriptions

Continuous polling adapters that feed new items into `raw/subscriptions/<type>/<item>.md` with a `pending: true` tag. The agent sees them via the `subscriptions` MCP tool.

**The concrete design — platform-by-platform mechanics, polling cadences, the Twitter tiers, paid-newsletter IMAP setup, the inbox UX, and failure handling — lives in its own document: `09_subscriptions_and_feeds.md`. The sub-bullets below are a sketch; that doc is the authoritative spec.**

#### `newsletter` — IMAP-based
Config: IMAP server, account, password (OS keyring), folder, from-address allowlist.
Polls the IMAP folder, converts matching emails to markdown (keeping HTML as fallback), stores under `raw/subscriptions/newsletter/YYYY-MM-DD-subject.md`.

Workflow: user creates a filter in their email client routing newsletters to a dedicated folder, gives alexandria read access to that folder, and the adapter pulls them without touching anything else.

#### `twitter` / `x-feed`
Config: usernames or list IDs.
Two modes:
- **RSS via nitter / rss.app** — no auth, polls per cadence.
- **Official API** — if the user has a developer token.
Stores tweets as markdown snippets under `raw/subscriptions/twitter/<handle>/YYYY-MM-DD-<id>.md`. Threads collapse into one file.

#### `rss` — generic RSS/Atom
Config: feed URL, optional since-cursor.
The fallback for any feed-shaped source: blog posts, podcasts (description + show notes), YouTube channels (title + description), GitHub release feeds.

#### `youtube`
Config: channel ID, transcript flag.
Uses the RSS feed for metadata; optionally fetches transcripts via `youtube-transcript-api`.

## Sync vs ingest — deliberate separation

**Sync** is background work: the adapter pulls content into `raw/`. No LLM calls. No wiki writes. Can run scheduled, unattended.

**Ingest** is agent work: the user asks the guardian to turn raw sources into wiki pages. LLM calls. Wiki writes. Cascade updates.

Separating them:
- Keeps token spend tied to user intent.
- Sync failures don't corrupt the wiki.
- The user can preview raw content before the agent touches it.
- Different adapters poll at different cadences without impacting the wiki.
- Subscriptions can deliver "inbox-style" — the agent sees N pending items and asks the user what to do with them.

## Scheduling and the daemon

The daemon runs an `apscheduler` with one job per active source/subscription:

- SOURCE adapters: configurable cadence, default "manual only" (sync on user trigger).
- SUBSCRIPTION adapters: default cadence per type (newsletter: hourly, twitter: 30 min, rss: 4 hours, youtube: daily). Configurable per adapter.
- Webhooks short-circuit the cadence when a provider pushes to `http://localhost:<port>/webhooks/<adapter>/<signature>`.

Without the daemon, the user runs `alexandria sync` and `alexandria subscriptions poll` manually. Same code path, just invoked from the CLI instead of the scheduler.

## Bidirectional storage — how "sync with" works

For STORAGE-kind adapters (Drive, S3, Dropbox, GCS, Notion), the user can configure a workspace to **push** its wiki to the external store:

```toml
[[workspaces.customer-acme.storage]]
type = "google-drive"
folder = "Acme/WorkingDocs"
mode = "push"
format = "obsidian-zip"   # or "raw-markdown" or "html"
cadence = "15m"
```

On every cadence tick (or `alexandria export --push`), the daemon:
1. Runs the `export` pipeline for the workspace into a temp dir.
2. Diffs against the adapter's `last_push_manifest.json`.
3. Pushes changed files via the adapter's `push()` method.
4. Updates the manifest.

Pushes are one-way: the same adapter can also be a SOURCE (reads come from a different root path), but the two modes don't cross. We never re-ingest our own exports.

## Lineage — every raw file is traceable

Every raw file records (in SQLite):
- `adapter_type`, `adapter_id`, `source_run_id`
- `external_id` (stable ID in the source system)
- `content_hash` (sha256 — drives incremental re-sync; copied from `reference/04_atomicmemory_compiler.md`)
- `original_url`
- `fetched_at`
- `content_type`
- `superseded_by` (nullable — re-sync creates a new row, marks the old)

Re-syncing does NOT delete the old row. It marks it `superseded_by` and inserts a new one. Wiki pages may still cite the superseded version; lint surfaces them via the "stale claim" heuristic.

## Credentials

All secrets live in `~/.alexandria/secrets/` as encrypted JSON. The master key comes from the OS keyring (`keyring` package — Secret Service on Linux, Keychain on macOS, Credential Locker on Windows). Failing that, a passphrase prompt.

No secret ever appears in `config.toml`. Adapter config holds a `secret_ref` that resolves via the secrets store.

## Security notes

- **Allowlist HTTP** — the `url` adapter and newsletter fetchers use a resolver that refuses private IPs (no SSRF to local services).
- **Rate limiting** — adapters back off on 429/503. Per-adapter concurrency caps in the scheduler.
- **Sandboxed clones** — git clones into per-run temp dirs, size capped.
- **Read-only by default** — STORAGE adapters require an explicit `mode = "push"` flag before any write happens.
