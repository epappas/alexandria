# Source: Google Calendar API v3 — Events.list reference

- **URL:** https://developers.google.com/workspace/calendar/api/v3/reference/events/list
- **Fetched:** 2026-04-15
- **Purpose:** determine the OAuth model and incremental-sync mechanism for the llmwiki calendar adapter.

---

## OAuth scope (read-only)

- **Primary:** `https://www.googleapis.com/auth/calendar.readonly`
- Also available (narrower): `calendar.events.readonly`, `calendar.events.public.readonly`, `calendar.events.owned.readonly`

`calendar.readonly` is the right choice for llmwiki — it covers all calendars the user owns or is subscribed to, with no write access.

## Key query parameters

| Parameter | Purpose |
|---|---|
| `timeMin` / `timeMax` | Window selection (past events, future events, specific periods) |
| `singleEvents` | Expand recurring events into instances — we want this for event-stream ingest |
| `orderBy` | `startTime` or `updated` — use `updated` for incremental polling |
| `updatedMin` | Fallback if we don't have a syncToken yet |

## Incremental sync — the important bit

> "Token obtained from the `nextSyncToken` field returned on the last page of results from the previous list request"

Google Calendar provides **`syncToken`**-based incremental sync. Every full list response returns a `nextSyncToken`; subsequent requests pass it to get only the deltas (new, modified, deleted events). Deleted entries are always included when using `syncToken`. This is exactly the primitive we need — zero wasted API calls on re-polls.

## Implication for llmwiki

The Calendar adapter stores `sync_token` per calendar in `source_adapters.metadata`, requests deltas on every poll, and only falls back to full re-list if the token expires (Google returns 410 Gone, which we handle by doing a fresh list with `timeMin = now - N days`).

Fields on each event (from the Events Resource): `summary` (title), `description`, `location`, `start` / `end` with timezone, `attendees[]` with response status, `conferenceData` (Meet/Zoom link), `creator`, `organizer`, `status` (confirmed/tentative/cancelled), `recurringEventId`, `iCalUID`. Plenty for llmwiki's "meeting happened" records.

Cadence: every 5–15 minutes is reasonable; sync tokens make polling cheap.
