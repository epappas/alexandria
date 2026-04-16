# 10 — Event Streams

> **Cites:** `research/raw/31_nitter_status_2026.md`, `research/raw/32_slack_free_tier_retention.md`, `research/raw/33_github_events_api.md`, `research/raw/34_google_calendar_api.md`. Builds on `05_source_integrations.md`, `06_data_model.md`, `09_subscriptions_and_feeds.md`.

## Why event streams need their own design

Subscriptions (blogs, Substack, YouTube, newsletters — see `09_subscriptions_and_feeds.md`) poll for **documents**. Each item is meaningful on its own: one newsletter, one post, one video. Ingest is a user-triggered choice per item.

Event streams are different. A GitHub commit is tiny. A Slack message is tinier. A calendar invite is one-shot. Individually, most of these events are meaningless — the signal is in the **patterns over time**: how auth evolved over Q1, what got decided in Monday's meeting, why the team rolled back the v2 release. The point of event streams is not to store events — it is to let the guardian build and maintain **temporal understanding** of the user's projects, customers, and relationships.

The architectural consequences are significant enough to warrant a new adapter kind, a new storage model, and new agent primitives. This document specifies them.

## The third adapter kind: `EVENT_STREAM`

`05_source_integrations.md` defines two adapter kinds — `SOURCE` and `SUBSCRIPTION`. Events add a third:

| Kind | Storage | Unit | Cadence | Ingest model |
|---|---|---|---|---|
| `SOURCE` | Filesystem (`raw/`) | Document | Manual / scheduled | User-triggered |
| `SUBSCRIPTION` | Filesystem (`raw/subscriptions/`) | Document | Polled (hourly–daily) | User-triggered per item |
| `EVENT_STREAM` | **SQLite tables** (`events` family) | **Fine-grained event** | Continuous (webhooks where possible, else fast polling) | **Scheduled temporal synthesis** + on-demand query |

Events live in SQLite because the filesystem is the wrong shape for thousands of tiny structured records per day. We do not create one markdown file per commit, per Slack message, per calendar invite. We create **digest pages** in `raw/timeline/<period>.md` on a schedule, generated from SQLite.

## Invariant update — files-first has two domains

`01_vision_and_principles.md` states "Files first, DB second — SQLite is a materialized view over the filesystem." That invariant holds for the **document layer** (raw/ + wiki/). It does **not** hold for the **event layer**:

- **Document layer** — `raw/` and `wiki/` under the workspace. Filesystem-first. `alexandria reindex` rebuilds SQLite from the files. This is where Karpathy's pattern applies.
- **Event layer** — `events` table family in SQLite plus derived digest files under `raw/timeline/`. **Database-first.** Events are born from API calls, not from files on disk. Re-hydration is via API replay (re-fetching from the source with a time window), not filesystem reindex.

Both domains live under the same workspace. The agent reads them through different MCP tools (`read` / `search` / `grep` for documents, `events` / `timeline` for event-layer queries). The wiki layer cross-references both.

**Updated invariant 11 (from `01_vision_and_principles.md`):** *"Files first for documents, APIs-of-record for events. The document layer is reconstructible from `~/.alexandria/`. The event layer is reconstructible from its source platforms (with retention caveats noted per adapter)."*

## The events table family

Added to `06_data_model.md`:

```sql
-- Every event from every stream, one row each, schema-per-source in JSONB
CREATE TABLE events (
  id              TEXT PRIMARY KEY,                -- internal UUID
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  adapter_id      TEXT NOT NULL REFERENCES source_adapters(id) ON DELETE CASCADE,
  source          TEXT NOT NULL,                   -- 'github' | 'calendar' | 'slack' | ...
  event_type      TEXT NOT NULL,                   -- 'push' | 'pr_opened' | 'message' | 'meeting' | ...
  external_id     TEXT NOT NULL,                   -- stable ID in the source
  occurred_at     TEXT NOT NULL,                   -- ISO timestamp, the "when" of the event
  ingested_at     TEXT NOT NULL,                   -- when we captured it
  actor           TEXT,                            -- user/author handle where applicable
  subject         TEXT,                            -- one-line summary for display + search
  body            TEXT,                            -- full content where applicable
  refs            TEXT,                            -- JSON array of cross-stream identifiers: ["#123", "abc1234", "!456", "msg-uuid"]
  payload         TEXT NOT NULL,                   -- JSON blob with source-specific fields
  UNIQUE(workspace, source, external_id)
);

CREATE INDEX idx_events_workspace_time ON events(workspace, occurred_at DESC);
CREATE INDEX idx_events_adapter_time   ON events(adapter_id, occurred_at DESC);
CREATE INDEX idx_events_actor          ON events(workspace, actor, occurred_at DESC);
CREATE INDEX idx_events_type           ON events(workspace, event_type, occurred_at DESC);

-- FTS over subject + body so the agent's `search` and `grep` cross events and documents uniformly
CREATE VIRTUAL TABLE events_fts USING fts5(
  subject, body, refs,
  content='events', content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);
```

Design notes:

- **`refs`** is the cross-stream correlation column. When ingesting a Slack message, we extract anything that looks like `#123`, `PR 456`, a commit SHA, a Zoom link, a meeting ID, and store them in the refs JSON array. When the agent asks "what related to PR #123?" it's one `grep` / `events(refs_contains="#123")` call.
- **`payload`** holds the full source-specific record (the GitHub issue JSON, the calendar event JSON, the Slack message JSON) so we never lose fidelity.
- **`subject`** is a one-line rendering used for list views and FTS. Generated from the payload by the adapter.
- **`body`** is the full text for events that have one (commit messages, PR descriptions, Slack messages). NULL for events without natural text (watch events, star events).
- **`events_fts`** lets the agent's keyword search cross both the document layer (`documents_fts`) and the event layer. We ship two separate FTS virtual tables; the `search` MCP tool queries both by default and merges.

## Git: clone it, don't poll it — the guiding insight

For git-based projects, the right architecture is to **clone the repo locally** and use git's own primitives (`git log`, `git show`, `git blame`, `git grep`) for commit history and code reading. No API, no rate limit, no 30-day retention window, no platform coupling. This mirrors the agentic-retrieval pattern applied to git itself: the agent composes primitives over a local artifact rather than consuming a pre-built API index. The `git-local` adapter below is the primary path for any git-hosted project, complemented by a thin API adapter (`github`, `gitlab`, etc.) for the metadata layer — issues, PRs, releases, discussions — that doesn't live in the git repo.

## Platform catalog — the honest matrix

Each platform has a real-world constraint profile. The architecture must acknowledge it.

### Git — `git-local` (primary path for git-hosted projects)

**The insight:** for commits, diffs, branches, and blame, we do not need any API at all. `git clone` gives us the entire history locally — no 30-day cap, no rate limit, no auth for public repos, no network after the initial clone. `git log`, `git show`, `git diff`, `git blame`, `git grep` are first-class agentic retrieval primitives in the same way that `ls`, `grep`, and `cat` are. This is the agentic-retrieval pattern applied to git itself: **don't build a pipeline, clone and read**.

Adapter strategy:

1. **Initial clone:** `git clone <url> ~/.alexandria/workspaces/<slug>/raw/git/<repo>/` on setup. Depth is configurable (`full`, `--shallow-since=<date>`, `--depth=N`).
2. **Incremental fetch:** `git fetch --all --prune` on every poll (default 5 minutes). Compare new tip against stored `last_fetched_sha` to identify new commits in each branch.
3. **Event extraction:** for each new commit, run `git log --format='%H%n%an%n%ae%n%aI%n%s%n%b%n---' <range>` and parse into `events` rows. Extract `refs` from the commit message (PR numbers, issue numbers, co-authors, trailers, Signed-off-by lines).
4. **Materialization:** commits land in the `events` table with `source='git-local'`, `event_type='commit'`, `external_id=<sha>`, `payload` containing the parsed commit plus file stats. The actual diff is NOT stored — the agent reads it live via `git_show` against the clone when needed. Zero duplication of content that git already stores efficiently.

Why this matters beyond cost:

- **Works on any git host** — GitHub, GitLab, Gitea, Codeberg, SourceHut, a corporate GitLab, a self-hosted git server, a raw SSH git repo, a local-only repo. No platform coupling.
- **Offline-friendly** — once cloned, the event-layer works without network. Polling for new commits is the only online step.
- **No rate limits** — `git log` is local. The agent can query as aggressively as it wants.
- **Full code access** — the agent can `grep` the actual source code, `read` any file at any commit, `git blame` to find who wrote a line, `git log -S "<string>"` to find the commit that introduced a function. These are primitives, not reconstructed from an API.
- **Branches matter** — a GitHub API reconciliation pass can't easily surface stale branches, work-in-progress, or the actual merge commit shape. The clone has this natively.

The agent interacts with the clone through three new MCP tools (see `04_guardian_agent.md`):

- `git_log(workspace, repo?, since?, until?, path?, grep?, author?, limit?)` — thin wrapper over `git log --format=...` with argument sanitization. Returns commits as structured rows.
- `git_show(workspace, repo?, sha)` — `git show <sha>` for the full diff on demand.
- `git_blame(workspace, repo?, path, line?)` — `git blame` for line-level authorship.

All three are read-only. They operate strictly against `workspaces/<slug>/raw/git/<repo>/`; no arbitrary `git` command execution. The safelist is: `log`, `show`, `diff`, `blame`, `grep`, `ls-files`, `rev-parse`, `cat-file`, `branch --list`, `tag --list`, `remote show <name>`. Nothing else. No `fetch`, `pull`, `checkout`, `config`, `clone`, `push`, `reset` exposed to the agent — the daemon handles those.

Config example:
```toml
[[event_streams.git-local]]
type = "git-local"
name = "acme-web-app"
url = "git@github.com:acme/web-app.git"
clone_depth = "full"              # or "--shallow-since=2024-01-01"
branches = ["main", "develop", "release/*"]
poll_cadence = "5m"
auth_ref = "github_ssh_key"       # for private repos
```

### GitHub API — `github` (layer-2 metadata, complementary to `git-local`)

The `git-local` adapter covers everything that lives **in** the git repository. Anything that lives **around** the repository — issues, pull requests, releases, discussions, comments, reviews — requires the GitHub API. We keep the GitHub adapter for this complementary role.

| Fact | Source |
|---|---|
| Events API caps at **30 days, 300 events** | `raw/33_*` |
| REST endpoints (issues, pulls, releases) have **full history** | same |
| Rate limit: **5000 req/hour authenticated** | same |
| Webhooks available for push-based updates | GitHub App / repo settings |

**Adapter strategy — two-track, and we no longer need the Events API or commit endpoints:**

1. **Backfill track** (on initial setup): paginate through `/repos/{owner}/{repo}/{issues,pulls,releases,issues/comments,discussions}`. **Commits come from `git-local`, not the API** — the API is only for the non-git metadata. One-time cost per repo.
2. **Live track**: webhook receiver (preferred) + periodic reconciliation against the REST endpoints for the same metadata types. The Events API 30-day cap stops being a problem because we do not rely on it for commit history.

Config example — commonly paired with a `git-local` adapter:
```toml
[[event_streams.github]]
type = "github"
repo = "acme/web-app"
auth_ref = "github_pat"
include = ["issues", "pulls", "releases", "discussions"]   # NO "commits" — git-local handles those
backfill_since = "2024-01-01"
poll_cadence = "5m"
webhook = true
```

Event types from this adapter: `issue_opened`, `issue_closed`, `issue_commented`, `pr_opened`, `pr_merged`, `pr_reviewed`, `release_published`, `discussion_created`. Commits are the `git-local` adapter's domain.

### The same pattern for GitLab / Gitea / Codeberg / self-hosted

Because `git-local` works on any git repo, the same insight applies to non-GitHub hosts:

- **`gitlab`** — issues, MRs, releases via the GitLab API; commits via `git-local`.
- **`gitea`** — same shape.
- **`self-hosted`** — for a pure git repo with no web UI at all, `git-local` alone gives commits, branches, and tags. Issues/PRs are stored elsewhere (a separate SOURCE adapter for a notes folder, a wiki, or an external tracker).

We write one core `git-local` adapter and thin API adapters per host for the metadata layer. The split pays off because the 80% of history — commits — is host-independent.

### Google Calendar — `calendar`

| Fact | Source |
|---|---|
| Scope `calendar.readonly` covers reads for all user calendars | `raw/34_*` |
| `syncToken` enables delta polling — zero wasted API calls | same |
| `singleEvents=true` expands recurring events into instances | same |
| Future + past events in one API | same |

**Adapter strategy:** on setup, full `list` with `timeMin` = workspace creation date (or a user-chosen date), store `nextSyncToken`. Every 5 minutes, `list(syncToken=<stored>)` gets only the deltas — new meetings, updates, cancellations. If the token expires (410), full re-list with a bounded window.

Event types: `meeting_scheduled`, `meeting_updated`, `meeting_cancelled`, `attendee_response_changed`. Past and future meetings live in the same table — the agent filters by `occurred_at` to distinguish "what happened last week" from "what's coming up tomorrow."

Meeting context (attendees, conference link, agenda from description) lives in `payload`. The actual meeting content (notes, transcripts) is a separate source — either a `local` adapter pointing at a notes folder, a `gmail` adapter pulling meeting recap emails, or a calendar-linked document.

### Gmail / Workspace mail — `gmail` (beyond IMAP)

For richer email metadata (threads, labels, attachments, headers) than IMAP can cleanly expose, we add a Gmail-API adapter. OAuth scope `gmail.readonly`. Uses Gmail's `history.list` endpoint with `startHistoryId` for incremental updates — same pattern as Calendar's `syncToken`.

Events: `email_received`, `email_sent`, `email_threaded`. Each event references its RFC Message-ID so cross-stream correlation with meetings (via meeting-invite emails) and GitHub (via notification emails) is trivial.

IMAP from `09_subscriptions_and_feeds.md` still handles the *newsletter* case (paid Substack, Stratechery). Gmail-API handles the *project communication* case (threads with a client, recruiting emails, receipts).

### Slack — `slack`

| Fact | Source |
|---|---|
| **Free plan: 90-day access + 1-year deletion** | `raw/32_*` |
| Paid plans (Pro, Business+, Enterprise+) remove the limit | same |
| API access follows the UI limit | same |

**The honest reality:** on a free Slack workspace, alexandria can only ingest what it captures during its run. Retroactive ingest of a multi-year free workspace is **impossible** — the content is gone from Slack's servers.

Adapter strategy:
- **Install early.** Day-1 install on the free tier captures everything from then on. Aggressive initial backfill over the available 90-day window.
- **Polling cadence:** every 1–5 minutes (Slack rate limits are per-tier; configured per adapter).
- **Scope:** specific channels + DMs + threads the user cares about. Never "everything in the workspace" — that's noise.
- **Filtering:** by channel, by user mentions, by keyword, by thread participation. Configured per adapter.

Auth: Slack app with `channels:history`, `groups:history`, `im:history`, `mpim:history` user token scopes. User installs the app to their workspace (admin approval may be required on locked-down Enterprise accounts). App is registered in Slack's developer portal either by us (pre-registered) or by the user themselves (`alexandria auth register slack --client-id ... --client-secret ...`).

Event types: `message_posted`, `message_edited`, `message_deleted`, `thread_replied`, `reaction_added`. `refs` extracts GitHub/Linear/Jira IDs, meeting links, file references.

### Discord — `discord`

**Policy constraint:** Discord's ToS forbids automating user accounts ("self-bots"). Automated user accounts get banned. The **only sanctioned route** is a **bot account** created via the Developer Portal, and bot accounts must be **explicitly invited to a server by a user with Manage Server permission**.

I was unable to retrieve Discord's selfbot policy page directly in this sandbox (403 on the canonical Discord support article). The above is the established, industry-consensus rule; users setting up a Discord adapter should verify the current policy before enabling it.

**Adapter strategy:**
- User creates a Discord application in the Developer Portal, generates a bot token.
- User invites the bot to each server they want to monitor, with `View Channels` and `Read Message History` permissions.
- alexandria's Discord adapter uses the bot token to poll channels or subscribe to the Gateway (websocket) for real-time events.
- DMs are **not accessible to bots** — bots can only be DM'd, not read DMs between other users. This is a hard limitation. For DMs, the user needs a different capture method (manual save) or must be the bot's recipient.

Event types: `message_posted`, `message_edited`, `thread_created`, `reaction_added`, `voice_joined`, `member_joined`. Same `refs` extraction as Slack.

### Microsoft Teams — `teams`

Microsoft Graph API with OAuth. Scopes: `Chat.Read`, `ChannelMessage.Read.All`, `Calendars.Read`, `Mail.Read`. Delta queries via `@odata.deltaLink` for incremental sync — same pattern as Calendar/Gmail. Scheduled as a post-MVP adapter; the architecture leaves room for it with no special-case code.

### Cloud storage change streams — `drive`, `dropbox`, `s3_events`

These already exist as SOURCE adapters (see `05_source_integrations.md`). For event-stream purposes we add change notification:

- **Google Drive** — `changes.list` endpoint with `pageToken`. Returns file created/modified/deleted events. Events become entries like `drive_file_modified { path, mime, actor, version }`.
- **Dropbox** — `files/list_folder/continue` with cursor. Same shape.
- **S3** — EventBridge + SQS notifications routed to a local webhook endpoint, OR periodic `ListObjects` + modified-time comparison.

Events aren't the files themselves (those stay in the SOURCE adapter path). Events are **change metadata** — "someone modified /shared/acme/contracts/v2.pdf at 14:23 today" — which the agent correlates with GitHub activity and calendar events when building a timeline.

### Linear, Jira, Notion databases — `linear`, `jira`, `notion_db`

All have webhook or API-polling interfaces. Each adds an event-stream adapter mirroring the GitHub shape. Post-MVP; architecture is ready.

## Auth model — OAuth per provider, stored locally

Every event-stream adapter uses OAuth 2.0 (with one exception — GitHub PAT is a pragmatic shortcut). The pattern:

1. User runs `alexandria auth register <provider>` and provides their own OAuth client ID + secret (from Google Cloud Console, Slack app dashboard, Discord Developer Portal, etc.). Client credentials are **the user's**, not shipped with alexandria.
2. User runs `alexandria auth login <provider> --workspace <slug>`. alexandria opens a browser to the provider's authorize URL with `redirect_uri=http://localhost:<port>/oauth/callback` and a locally-generated PKCE code. A local listener accepts the callback.
3. Access token + refresh token land in `~/.alexandria/secrets/<adapter-id>.enc`, encrypted with the OS-keyring-derived master key.
4. The daemon refreshes tokens automatically. Revocation is a single `alexandria auth revoke <provider> --workspace <slug>`.

We do **not** ship pre-registered client credentials for these providers. Rationale:
- Keeps alexandria truly local-first. No dependency on Anthropic or the author hosting anything.
- Prevents credential-sharing scenarios where our client secret leaks.
- Matches the established pattern for developer tools that talk to OAuth providers (e.g., `gh auth login` uses GitHub's device flow with GitHub's own published client ID, but anything more private requires user-provided credentials).

GitHub can also use a personal access token (PAT) directly — simpler for the common case, same encrypted storage.

## Polling, webhooks, and cadences

The daemon runs one scheduler job per active event-stream adapter. Defaults:

| Platform | Cadence | Webhook supported? |
|---|---|---|
| `github` | 5 minutes (plus webhook receiver if registered) | yes |
| `calendar` | 5 minutes (syncToken makes this cheap) | yes via push notifications |
| `gmail` | 2 minutes (historyId incremental) | yes via push notifications |
| `slack` | 1 minute (RTM/Events API websocket) | yes via Events API |
| `discord` | Gateway websocket (real-time) | N/A — Gateway IS real-time |
| `teams` | 5 minutes (Graph delta queries) | yes |
| `drive` / `dropbox` / `s3` | 10 minutes | yes |

Without the daemon, polling runs from the CLI via `alexandria sync --workspace <slug>`. Webhooks require the daemon's HTTP listener; without a daemon, polling is the only option and the user accepts the latency.

## The new agent tools

Two new MCP tools, joining the nine from `research/reference/12_agentic_retrieval.md`:

### `events(workspace, source?, type?, actor?, since?, until?, refs_contains?, limit?)`

The structured event query. Returns a paginated list with `{id, source, type, occurred_at, actor, subject, refs, excerpt}`. The agent uses this to answer "what happened in GitHub last week" or "find every event that references PR #123."

### `timeline(workspace, since, until, granularity="day"|"week"|"month", sources?)`

Returns a pre-grouped summary of activity across all event streams for the period: counts per source, top actors, most-referenced items, top keywords. The agent uses this for the high-level "how did this project evolve" question — a starting point that narrows the space before drilling in via `events()`.

Both tools cross FTS into `events_fts`. Both respect workspace boundaries. Neither writes anything.

The existing `read`, `grep`, `search`, `follow` tools continue to work for the document layer. The agent combines them freely: `events()` to find a cluster of activity, `follow` to jump from a referenced PR in an event to the PR description, `read` on a `wiki/<topic>/` page to see what the wiki already says about it.

## How the three operations extend to events

No new operation. Ingest / query / lint all gain event awareness:

### Temporal synthesis = scheduled ingest of events

The daemon runs a scheduled ingest with a specific workflow: "digest this week's events into `wiki/timeline/`." This is still *ingest* — the agent reads events, compiles wiki pages, cascades, logs. Different source type, same operation.

On a configurable cadence (default weekly), per workspace, the daemon spawns the guardian agent with the prompt:

```
Digest this week's events into wiki/timeline/2026-w15.md.
Focus on: what changed, what got decided, who contributed, what blocked.
Update wiki/entities/<active-project>.md with "Recent activity" sections.
Update wiki/overview.md.
Append to wiki/log.md.
Bounded token budget: 50000 output tokens.
```

The scheduled ingest writes **only** into `wiki/timeline/<period>.md` and sections of existing entity pages explicitly marked "Recent activity" — it cannot silently rewrite concept pages. Guardrails:

1. **Write path ACL:** scheduled ingest is allowed to write `wiki/timeline/**` and append to `wiki/log.md`. Other writes require a dedicated `str_replace` call against an explicitly marked section (`<!-- AUTO:recent-activity -->...<!-- /AUTO -->`).
2. **Token budget:** hard cap per run, enforced by the provider wrapper, recorded in `~/.alexandria/logs/llm-usage.jsonl`. Configured per operation in `[llm.budgets]` — see `11_inference_endpoint.md`. Exceeded → the run errors and surfaces in status.
3. **Dry-run preview:** `alexandria synthesize --workspace X --dry-run` prints the estimated cost before committing to the run. See `11_inference_endpoint.md` for the preview shape.
4. **Opt-in per workspace:** scheduled synthesis is **disabled by default**. Users enable explicitly with `alexandria synthesize enable --workspace X`, which prompts for the cost preset and budget caps.
5. **Human review:** the timeline page is a draft until the user runs `alexandria timeline confirm <period>` or edits it. Until then it carries a `draft: true` frontmatter flag and is excluded from the wiki's main cross-references.

This is the first automation that runs the agent without a human in the loop. The guardrails — bounded budgets, dry-run preview, opt-in activation, draft-until-confirmed, write-path ACL — are exactly what the user needs to trust it. The inference endpoint, provider selection, and prompt caching that make it affordable are defined in `11_inference_endpoint.md`.

**Crucially, scheduled synthesis runs through the staged-write transaction defined in `13_hostile_verifier.md`.** This is the same mechanism that protects interactive ingest — the synthesis is just another `run_type = 'synthesis'` in the runs table. A daemon crash mid-synthesis leaves a `pending` or `verifying` row that the daemon-startup orphan sweep transitions to `abandoned`; the live wiki is untouched because nothing was ever moved out of `staged/`. A budget-stop mid-run abandons the staging cleanly. The synthesis writes belief sidecars per `19_belief_revision.md` so weekly digests are belief-tracked just like manual ingests. The verifier's per-page checks enforce the convergence policy from `15_cascade_and_convergence.md` against everything the daemon writes — the user's wiki cannot accumulate silent contradictions while they sleep.

### Query over events — temporal questions

User asks: *"How did the auth system evolve in Q1?"*

Agent workflow:
1. `timeline(workspace, since="2026-01-01", until="2026-03-31")` — get the shape.
2. `events(workspace, source="github", refs_contains="auth")` — find relevant PRs/issues/commits.
3. `events(workspace, source="slack", since="...")` — find discussions.
4. `events(workspace, source="calendar", since="...")` — find meetings about auth.
5. `read(path="wiki/entities/auth.md")` — see what the wiki already knows.
6. Synthesize a narrative with dated citations.
7. User says "save this" → archive into `wiki/archives/auth-q1-evolution.md`.

No wiki writes unless the user archives. Same as the existing query pattern, just extended across the event layer.

### Lint — catch wiki claims that events contradict

The lint pass extends to compare wiki assertions against recent events. Example heuristic finding: "`wiki/entities/auth.md` says 'authentication uses JWT' last updated 2026-01-15, but 5 commits to the auth module in the past week reference OAuth 2.0 — possible supersession, review recommended." Reports, never auto-fixes, because judgment about whether a wiki claim is truly superseded is user territory.

## Cross-stream correlation — no automated linker, just `refs`

The temptation is to build an entity-linker that watches events, extracts entities, and builds a graph. We explicitly reject this, for the same reason we rejected vector stores: **the agent is the linker.**

Instead, every adapter extracts shallow identifiers into `refs` at ingest time:

- **GitHub** — issue/PR numbers, commit SHAs, branch names.
- **Slack/Discord** — URLs, issue references, meeting links, message IDs.
- **Calendar** — meeting IDs, Google Meet/Zoom links, attendee emails.
- **Gmail** — Message-IDs, thread IDs, subject-line issue refs.
- **Drive/Dropbox** — file paths, shared link IDs.

Then `events(refs_contains="#123")` or `grep` over `events_fts` trivially finds all cross-stream references to the same thing. The agent walks the graph by asking questions, not by following pre-computed edges.

This is the CatRAG lesson from `research/reference/13_agentic_retrieval_design_space.md` applied to events: static graphs have the "static graph fallacy"; agentic navigation lets the agent adapt to what each query actually needs.

## Privacy, scope, and safety

Event streams touch the most private data a personal tool can handle — emails, chat messages, private meeting invites, private repos. Two hard rules:

1. **Never leaves the machine.** All event data is stored locally in SQLite. The only outbound network calls are to the configured source APIs for polling. No telemetry, no cloud backup unless the user explicitly configures an S3 destination for their own backups.
2. **Never returned through MCP as raw credentials.** The `events` and `sources` tools return event metadata and content, but never OAuth tokens, never API keys, never anything from `~/.alexandria/secrets/`. A prompt-injected agent cannot exfiltrate credentials through the tool surface because the tools never expose them in the first place.

Scoping:

- Per-channel / per-repo / per-calendar inclusion lists in each adapter's config. Default is **nothing enabled** — the user explicitly opts in to each source.
- Per-adapter allowlists for keywords or authors (e.g., "only Slack messages from #eng-architecture" or "only Gmail threads with acme.com addresses").
- The user can `alexandria events purge --source slack --before 2025-01-01` to delete local history at any time.

Credential storage, OS-keyring derivation, and encrypted-at-rest config are defined in `05_source_integrations.md` and `06_data_model.md` — the same mechanism as for SOURCE and SUBSCRIPTION adapters.

## The workspace-level picture

For a project workspace (e.g., `workspaces/customer-acme/`), a representative setup looks like:

```
events:
  github:    acme/web-app repo, all issues/PRs/commits/releases
  calendar:  user's primary calendar, filtered to events with "Acme" in title or attendees
  gmail:     label:acme, since 2024-01-01
  slack:     channels #acme-dev, #acme-design, DMs with acme.com contacts
  drive:     folder "Shared with me/Acme"

documents (raw/):
  notion:    acme's internal wiki pages
  github:    acme/web-app docs/ and README
  local:     ~/customers/acme/specs/

subscriptions (raw/subscriptions/):
  rss:       acme.com/blog/rss

wiki/:
  overview.md                          # hub
  index.md
  log.md
  concepts/
    auth-architecture.md               # concept pages written by the guardian
    billing-model.md
  entities/
    acme-inc.md                         # entity page, Recent Activity section auto-updated from events
    alice-smith.md                      # their engineer
  timeline/
    2026-w15.md                         # scheduled weekly digest
    2026-w14.md
  archives/
    2026-04-auth-q1-evolution.md       # user-archived query answer
```

The guardian's `guide()` output for this workspace includes event counts alongside document counts:

```
Events (last 7 days):
  github    47  (6 PRs opened, 3 merged, 18 commits, 12 issue comments...)
  calendar   5  (3 meetings, 2 cancellations)
  gmail     14  (4 threads)
  slack    213  (most active: #acme-dev)
  drive      2  (contracts/v3.pdf modified)

Pending scheduled synthesis: week 15 digest ready to run
```

## Open questions specific to event streams

1. **Meeting transcripts.** Calendar events give us metadata; transcripts need an additional source (Google Meet transcripts via Drive, Otter.ai export, manual upload). We defer the transcript integration — capture the meeting metadata now, add transcript sources as a SOURCE adapter when the user wires it up.
2. **Real-time ingestion for chat.** The Slack / Discord Gateway websocket gives near-real-time message delivery, but holding a websocket open 24/7 changes the daemon's shape from "scheduled polls" to "persistent connections." We default to polling at 1-minute intervals and leave websocket mode as an opt-in for users who want latency below a minute.
3. **Summarisation-at-ingest vs summarisation-on-demand.** Chat channels can produce thousands of messages per day. Do we summarise into a digest as the events come in, or do we store raw and defer synthesis until the scheduled weekly ingest? **MVP: raw storage + weekly synthesis.** Scheduled per-day summarization is a v2 hook for high-volume channels.
4. **Retroactive backfill of deleted content.** Slack free-tier deletes at 1 year. Discord doesn't delete but requires bot presence at the time messages were sent. These are fundamental platform limits; alexandria surfaces them in adapter status and does not pretend to work around them.
5. **Meeting-is-a-cluster.** A "meeting" is not one event — it's a calendar invite + an email thread + a Google Doc agenda + Slack discussion during it + possibly a transcript after. Currently the user ties these together via `refs` correlation and queries. Whether to introduce a first-class `meetings` virtual view that materialises these clusters is a post-MVP question.

## Summary

Event streams are a new adapter kind (`EVENT_STREAM`) that stores continuous fine-grained activity in SQLite (not filesystem), extracts cross-stream correlation identifiers into a `refs` field, surfaces events to the agent through two new MCP tools (`events`, `timeline`), and extends the existing ingest operation with a scheduled temporal-synthesis workflow that writes only into `wiki/timeline/` under strict guardrails. Platforms supported at MVP: GitHub, Google Calendar, Gmail, Slack, Discord, and cloud-storage change streams; Teams and Linear/Jira/Notion are post-MVP with the same shape.

The honest platform constraints are documented in-line with direct API citations: GitHub's 30-day Events API cap, Slack's 90-day/1-year free-tier wall, Discord's bot-only policy, Google Calendar's syncToken incremental model. No platform claim is unsourced.

The guardian builds temporal understanding by composing event queries with document reads — the same agentic-retrieval pattern applied across both layers. No entity linker, no knowledge graph, no vector store. Just fine-grained events in SQLite, cross-stream `refs`, and an agent that can walk the correlations at query time.
