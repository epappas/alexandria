# 09 — Subscriptions and Feeds

> **Cites:** `research/raw/31_nitter_status_2026.md`, the SourceAdapter framing in `05_source_integrations.md`, the data model in `06_data_model.md`.

Subscriptions are continuous source adapters: newsletters, Substack / Ghost / WordPress blogs, YouTube channels, RSS feeds, Mastodon / Bluesky accounts, subreddits, podcasts, and (as a hard case) Twitter/X. The earlier `05_source_integrations.md` sketches the shape; this doc pins down the implementation, the realistic failure modes, and the user-facing UX.

## The honest platform matrix

Different platforms give you different amounts of signal. The architecture must be honest about which is which — no pretending that "we can follow anything" when the platform has made that false.

| Platform | Mechanism | Reliability | Content completeness |
|---|---|---|---|
| WordPress / Ghost / Hugo / Jekyll / 11ty blog | RSS / Atom | **High** — standards-based, stable for 20 years | **Full** in `<content:encoded>` or `<summary type="html">` |
| Substack (free posts) | `<name>.substack.com/feed` | **High** | **Full** |
| Substack (paid posts) | Same URL | **High** for the teaser | **Teaser only**; full content delivered by email. See "Paid newsletter via IMAP" below. |
| Medium blog | `https://medium.com/feed/@username` | **Medium** — Medium throttles | **Partial** — often excerpts. Fetch the page for full content. |
| YouTube channel | `youtube.com/feeds/videos.xml?channel_id=<ID>` | **High** — public endpoint | Metadata + description only. **No transcripts** — separate fetch via `youtube-transcript-api`. |
| Mastodon user | `<instance>/@<user>.rss` | **High** | Full post text |
| Bluesky user | AT Proto JSON feeds (needs client wrapper) or third-party RSS bridges | **Medium** | Full post text |
| Reddit subreddit | `/r/<sub>/.rss` | **Medium** — Reddit rate-limits | Title + link + teaser; fetch post JSON for full content |
| Podcast | Standard RSS 2.0 with `<enclosure>` | **High** | Metadata + audio URL; transcription is a separate concern |
| Newsletter (email-delivered) | IMAP against user's mail account | **High**, depends on user's mail provider | Full content inside the email |
| Twitter / X | **No official RSS.** See "The Twitter problem" below. | **Low** — no supported path | Varies |

**Verified facts (2026-04-15):**

- **Substack-style feeds** include full post HTML in `<content:encoded>` with inline images, embeds, and audio players. Paywalled items are distinguishable by markers in the DOM (e.g. `<div class="wp-block-passport-restricted-content">`). *Verified against `https://stratechery.com/feed/` via WebFetch.*
- **Modern blog feeds** (Simon Willison's Atom feed as a control case) deliver Atom 1.0 with complete HTML in `<summary type="html">`. Full content, no fetch step needed. *Verified against `https://simonwillison.net/atom/everything/`.*
- **YouTube channel RSS** is a public, unauthenticated endpoint. Entries carry `yt:videoId`, `title`, `link`, `published`, `author`, `media:description`, `media:thumbnail` — no transcripts. *Verified against `https://www.youtube.com/feeds/videos.xml?channel_id=UCsBjURrPoezykLs9EqgamOA`.*
- **Nitter** still supports RSS, is still maintained, but **now requires real Twitter accounts for session tokens** — operational burden the user must take on themselves. *See `research/raw/31_nitter_status_2026.md`.*

## Adapter catalog

Subscriptions are SourceAdapter instances with `kind = SUBSCRIPTION`. The single generic `rss` adapter handles the vast majority of cases; convenience adapters exist to pre-fill configuration and set the right defaults.

| Adapter | Uses | When |
|---|---|---|
| `rss` | Generic RSS 2.0 / Atom 1.0 parser | Any feed that speaks RSS/Atom |
| `substack` | `rss` with `.substack.com/feed` URL template + paywalled-marker detection | User provides a Substack publication name |
| `wordpress` | `rss` with WordPress feed detection | User provides a WordPress site URL |
| `ghost` | `rss` with Ghost feed detection | User provides a Ghost site URL |
| `youtube` | YouTube RSS + optional `youtube-transcript-api` fetch | User provides a channel ID or handle |
| `mastodon` | `rss` against `<instance>/@<user>.rss` | User provides instance + handle |
| `bluesky` | AT Proto feed or third-party RSS bridge | User provides handle |
| `reddit` | `/r/<sub>/.rss` + optional `.json` fetch for full post content | User provides subreddit name |
| `podcast` | `rss` with enclosure handling | User provides feed URL |
| `newsletter` | IMAP against user's mail account | For paid Substack, Stratechery, any email-delivered content |
| `twitter-nitter` | Nitter RSS | User runs their own Nitter instance |
| `twitter-rsshub` | rsshub-style bridge | Low-volume casual following |
| `twitter-manual` | `llmwiki tweet-save <url>` CLI command using fxtwitter | Individual tweets the user wants to preserve |

## The generic RSS adapter — architecture

```python
class RSSAdapter(SourceAdapter):
    type = "rss"
    kind = AdapterKind.SUBSCRIPTION

    async def list(self, config, since):
        feed = feedparser.parse(config["url"])
        for entry in feed.entries:
            if since and parse_date(entry.published) <= since:
                continue
            yield SourceItem(
                external_id=entry.id or entry.link,
                path=entry.link,
                modified_at=parse_date(entry.updated or entry.published),
                content_hash=None,  # computed after fetch
            )

    async def fetch(self, config, item):
        entry = self._find_entry(item.external_id)
        # Content policy: use feed-provided content if present, else fetch the page
        if _has_full_content(entry):
            html = entry.content[0].value if entry.content else entry.summary
        else:
            html = await _fetch_page(entry.link)
        markdown = self._to_markdown(html)
        markdown = await self._download_images(markdown, destination_dir)
        return FetchedDocument(
            external_id=item.external_id,
            title=entry.title,
            content=markdown,
            mime="text/markdown",
            metadata={
                "url": entry.link,
                "published_at": entry.published,
                "author": entry.get("author"),
                "tags": [t.term for t in entry.get("tags", [])],
                "feed_title": feed.feed.title,
                "paywalled": self._detect_paywall(html),
            },
            hash=sha256(markdown.encode()).hexdigest(),
        )
```

Content policy:

1. **Feed has full content** (`<content:encoded>` or `<summary type="html">` with length above a threshold) → use it directly. Fast, respectful of the source, zero extra HTTP.
2. **Feed has teaser only** → fetch the page via our allowlisted HTTP client, run `readability-lxml` + `markdownify` to extract the article body, store both original HTML and clean markdown side-by-side in `raw/subscriptions/<adapter>/<item>/`.
3. **Paywall detected** → store the teaser, mark `paywalled: true` in metadata, and surface a message telling the user to configure the `newsletter` IMAP adapter for that publication if they want full content.

Image handling: every `<img>` in the HTML gets downloaded to `raw/subscriptions/<adapter>/<item>/images/<hash>.<ext>` and the markdown is rewritten to reference the local path. Rationale: archival integrity — a post's images may disappear, and the wiki must remain complete.

## Paid newsletter via IMAP — the real design

Paywalled Substack, paid-tier Stratechery, and similar publications deliver full content in the email version. The pattern:

1. User enables *"email me new posts"* on the paid subscription (Substack default; most providers support this).
2. User creates a mail filter routing these emails to a dedicated folder/label — e.g., Gmail label `llmwiki-newsletters`.
3. User generates an **app password** specifically for that label via their provider's scoped-access mechanism (Gmail → App passwords; Fastmail → App passwords; iCloud → App-specific passwords).
4. User adds an `newsletter` adapter to llmwiki: `llmwiki source add newsletter --imap-host imap.gmail.com --imap-user ... --imap-folder llmwiki-newsletters --from-allowlist "*@substack.com,*@stratechery.com"`.
5. llmwiki stores the credentials encrypted in `~/.llmwiki/secrets/` (keyring-derived master key; see `06_data_model.md`).
6. The daemon polls the folder hourly via IMAP IDLE (if supported) or STARTTLS+SELECT otherwise.

Per-email processing:

1. Filter by `From:` against the adapter's allowlist — everything else is ignored.
2. Extract HTML body, strip mail chrome (unsubscribe links, tracking pixels, "view in browser", template boilerplate) with a rule set per known publication.
3. Convert to markdown. Download embedded images same as the RSS path.
4. Save as `raw/subscriptions/newsletter/<publication>/<yyyy-mm-dd>-<subject-slug>.md` with metadata `{publication, author, email_date, message_id}`.

Known quirks per provider:

- **Gmail IMAP IDLE** is supported but requires app password, not the main password.
- **iCloud** requires app-specific password even with two-factor enabled.
- **Fastmail** has generous rate limits and supports IDLE cleanly.
- **Outlook/Office 365** now requires OAuth, not IMAP+password. We document this as a known limitation.
- **Self-hosted (Mu4e, Notmuch, Mailpile)** — just point the `newsletter` adapter at the local Maildir; no IMAP at all.

## The Twitter problem, honestly

There is no reliable, unauthenticated way to follow arbitrary Twitter/X accounts in 2026. The architecture provides three tiers and documents each one's trade-off:

### Tier 1 — `twitter-nitter` (most reliable, user owns the infrastructure)

The user runs their own Nitter instance on a VPS, laptop, or Docker container. They configure throwaway Twitter account(s) to provide session tokens (a current Nitter requirement per `raw/31_*`). llmwiki's adapter points at `https://nitter.theirhost.com/<user>/rss`.

- **Pro:** works reliably, no third-party dependency, respects the user's privacy choices.
- **Con:** non-trivial ops burden. Throwaway accounts get suspended; session tokens expire; Twitter actively fights this.
- **Who it's for:** users who seriously want to archive Twitter content and are willing to run infrastructure.

### Tier 2 — `twitter-rsshub` (low-volume casual following)

The user points the adapter at an rsshub-style bridge — either a public instance or their own. Feed URLs look like `https://rsshub.app/twitter/user/<handle>`.

- **Pro:** zero setup.
- **Con:** public instances are rate-limited, occasionally blocked, and subject to going dark without notice. Suitable for ~5 accounts and low-frequency polling.
- **Who it's for:** users who want to casually follow a handful of public Twitter accounts without running infrastructure.

### Tier 3 — `twitter-manual` (one tweet at a time, always works)

`llmwiki tweet-save <url>` — a CLI command that hits `api.fxtwitter.com` (the same public proxy we used to retrieve Karpathy's tweet for `raw/00_*`) and saves a single tweet verbatim to `raw/subscriptions/twitter-manual/<handle>/<yyyy-mm-dd>-<tweet-id>.md`.

- **Pro:** always works, no auth, no ops.
- **Con:** no feed — the user has to know which tweets to save.
- **Who it's for:** everyone. Even users on Tier 1 or Tier 2 will want this for the specific tweets they consciously choose to preserve.

We do **not** support the official X API. $100/mo for the basic paid tier is disproportionate for personal use, and the terms forbid redistribution anyway.

## Scheduling — the daemon's view

Subscriptions are the main reason the optional daemon exists. One `apscheduler` job per active source, with these defaults:

| Adapter | Default cadence | Reason |
|---|---|---|
| `rss`, `substack`, `wordpress`, `ghost` | 4h | Most blogs post at most a few times a day |
| `medium` | 6h | Medium is slower-moving |
| `youtube` | 24h | Channels rarely post more than once daily |
| `mastodon`, `bluesky` | 1h | Social-paced |
| `reddit` | 2h | Balance between freshness and rate limits |
| `podcast` | 6h | Episodes drop at most daily |
| `newsletter` (IMAP) | IDLE (~instant) where supported, else 1h | Mail is push where possible |
| `twitter-nitter` | 30m | User owns the rate limit |
| `twitter-rsshub` | 2h | Public instances require gentle polling |

All cadences are configurable per-adapter via the workspace config. The daemon respects per-host concurrency caps (e.g., max 1 concurrent request to any rsshub-like bridge).

Without the daemon, the same code runs manually: `llmwiki sync` and `llmwiki subscriptions poll` do the same work on demand.

## Deduplication, versioning, failures

All subscriptions use the `external_id` + `content_hash` machinery already defined in `06_data_model.md`:

- RSS `<guid>` / Atom `<id>` → `external_id`.
- Re-polls that see the same `external_id` with the same `content_hash` → skip.
- Same `external_id`, different `content_hash` (post was edited after publish) → new row, old row marked `superseded_by`. Relevant for blogs that update posts — the original citation in any wiki page remains valid, and lint surfaces the supersession so the user can decide.

Failure modes:

- **Feed unreachable (DNS, 5xx, timeout):** mark `source_adapters.status = 'error'` with `last_error`. Retain previously-fetched items. Retry per backoff policy.
- **Parser failure on a single item:** log to `~/.llmwiki/logs/sync-<date>.jsonl`, skip the item, continue the run.
- **Rate-limit hit:** exponential backoff per adapter. Cap retries. Mark `degraded` after N consecutive failures.
- **Credentials expired (IMAP app password revoked):** mark `auth_required`, surface in CLI/UI status, do not silently retry.
- **Content decoded as empty:** mark the item `suspicious`, keep the source URL, let the user investigate.

**No silent drops.** Every failure is logged, every degraded adapter is visible.

## The inbox UX — how the user and the agent see new items

### CLI

```
$ llmwiki subscriptions list --workspace research
12 pending subscription items across 4 sources:

  substack  Every                2 new   (free-full)
  newsletter Stratechery         3 new   (paid-via-imap)
  youtube   Fireship             1 new   (title+desc only)
  rss       simonwillison.net    6 new   (atom-full)

  $ llmwiki subscriptions show 3   # render one by title
  $ llmwiki subscriptions ingest --where "from:Every"   # trigger agent
  $ llmwiki subscriptions dismiss 7   # mark as read without ingesting
```

### Web UI (when daemon is running)

The dashboard has a **Subscription Inbox** page that groups pending items by source, shows titles + short excerpts, and offers three actions per item:

- **Read** — render the markdown in the browser.
- **Ingest** — trigger the guardian's ingest workflow for this specific item.
- **Dismiss** — mark `status = dismissed` in `subscriptions_queue`; the item remains in `raw/` for archival but is removed from the active queue.

Bulk operations work too: select items → "ingest selection" runs one agent session over the batch.

### The guardian agent

The `guide()` response includes a pending-subscriptions summary:

```
Pending subscription items: 12
  substack/Every: 2 new
  newsletter/Stratechery: 3 new
  youtube/Fireship: 1 new
  rss/simonwillison.net: 6 new
```

The agent has two MCP tools for working with subscriptions:

- `subscriptions(workspace, status="pending", since?, adapter?)` — lists pending items with `{path, title, adapter, published_at, excerpt}`.
- `read(workspace, path)` — same `read` tool used for any document; the subscription items live under `raw/subscriptions/...` and are read like any other raw source.

**Ingest is user-triggered, not automatic.** The user says *"read today's newsletters and compile the ones about distributed systems into my architecture wiki"* and the agent:

1. Calls `subscriptions(workspace, status="pending", since="1d")` to get the list.
2. Calls `read(path=...)` on each.
3. Filters to the relevant ones.
4. Runs the usual ingest workflow (new page or merge into existing, cascade updates, overview + log).
5. Moves the ingested items in `subscriptions_queue` from `pending` → `ingested`.
6. Items the agent decided were off-topic get `dismissed` or stay `pending` — user's choice.

## Triage and auto-ingest — explicitly not the default

A tempting but wrong move is to auto-ingest every subscription item. That turns a personal wiki into a dumping ground. The architecture's answer:

1. **Default: items stay pending until the user triggers ingest.** This preserves the user's role as curator.
2. **Opt-in per source:** `auto_ingest = true` in the adapter config. The daemon runs a headless ingest with a bounded token budget and a dry-run first. Recommended only for high-signal, low-volume sources (e.g., a single tracked RFC feed).
3. **Agent-driven triage:** the user can say *"look at the pending items and suggest what to ingest"* and the guardian reads titles + excerpts, proposes a selection, and waits for approval.

Auto-ingest is hedged against the fundamental problem that *most subscription content is not worth compiling.* The pattern's compounding property (explored in `research/reference/01_karpathy_pattern.md`) depends on signal over noise. A wiki built from everything the user ever subscribed to is worse than no wiki — it's the 2007 RSS reader problem all over again.

## What the agent can do at query time

Subscriptions aren't just a staging area for future ingest. They are readable by the guardian right now:

- **"What's new in AI this week?"** — `subscriptions(since="7d", adapter="rss|substack|newsletter")` → read titles/excerpts → synthesize.
- **"Summarise the three Every posts from yesterday."** — `subscriptions(since="1d", adapter="substack")` → `read` each → summary.
- **"Find the newsletter where they discussed CatRAG."** — `grep(pattern="CatRAG", path="/raw/subscriptions/**")` → `read` the match.

These are query-only. They don't touch the wiki layer unless the user explicitly asks.

## Privacy, safety, and credentials

- All credentials live in `~/.llmwiki/secrets/*.enc`, encrypted with a key derived from the OS keyring (see `06_data_model.md`).
- No credential is ever returned from the `sources` or `subscriptions` MCP tools. The agent sees adapter type, name, counts, and status — never tokens or passwords.
- HTTP fetches use an allowlisted resolver that refuses private IPs (no SSRF to local services from a malicious feed URL).
- IMAP clients use STARTTLS + IMAPS; plaintext IMAP is refused.
- Per-host concurrency caps prevent a runaway poll from getting llmwiki rate-limited or IP-banned.
- All fetches are logged to `~/.llmwiki/logs/sync-<date>.jsonl` with `{adapter_id, url, status, latency_ms, item_count}`. No content in the logs — only metadata.

## Summary

Subscriptions are SourceAdapters with continuous polling. Blog/Substack/YouTube feeds work cleanly via RSS/Atom. Paid newsletters work via IMAP against a scoped mail label. Twitter is fragile and we support three tiers honestly: self-hosted Nitter, rsshub-style bridges, or `llmwiki tweet-save` for individual tweets. Items land in `raw/subscriptions/...` as pending, the guardian sees them through the `subscriptions` MCP tool, and ingest is user-triggered by default. No auto-ingest unless the user opts in per source. No silent failures.
