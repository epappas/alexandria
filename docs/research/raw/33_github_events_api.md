# Source: GitHub REST API — Activity / Events

- **URL:** https://docs.github.com/en/rest/activity/events
- **Fetched:** 2026-04-15
- **Purpose:** determine what GitHub activity llmwiki can fetch and with what retention.

---

## The critical constraint (verbatim)

> "The timeline will include up to 300 events. Only events created within the past 30 days will be included."

**This is a hard 30-day, 300-event cap on the Events API.** It is not fixable via pagination or authentication.

## Available event-listing endpoints

1. `GET /events` — public events globally
2. `GET /networks/{owner}/{repo}/events` — repository network events
3. `GET /orgs/{org}/events` — organization public events
4. `GET /repos/{owner}/{repo}/events` — repository events
5. `GET /users/{username}/events` — user events (private if authenticated)
6. `GET /users/{username}/events/public` — public user events
7. `GET /users/{username}/received_events` — events a user receives
8. `GET /users/{username}/received_events/public` — public received events
9. `GET /users/{username}/events/orgs/{org}` — user's organization dashboard

## Event types returned

CreateEvent, DeleteEvent, DiscussionEvent, IssuesEvent, IssueCommentEvent, ForkEvent, GollumEvent, MemberEvent, PublicEvent, PushEvent, PullRequestEvent, PullRequestReviewCommentEvent, PullRequestReviewEvent, CommitCommentEvent, ReleaseEvent, WatchEvent.

## Implication for llmwiki

The Events API is for **recent activity only** — a 30-day rolling window. For historical project understanding, llmwiki must use the full REST API endpoints directly:

- `/repos/{owner}/{repo}/issues` — full issue history, paginated, no hard retention.
- `/repos/{owner}/{repo}/pulls` — full PR history.
- `/repos/{owner}/{repo}/commits` — full commit history (git itself, via API).
- `/repos/{owner}/{repo}/releases` — all releases.
- `/repos/{owner}/{repo}/issues/comments` — all comments.

These endpoints have no 30-day cap — they return everything, paginated.

**Architecture:** the GitHub adapter uses a two-track strategy:
1. **Backfill track** — on first sync, paginate through the full REST endpoints to build history.
2. **Live track** — once caught up, poll the Events API (or webhooks) for the fresh 30-day window. Fall back to the REST endpoints as a reconciliation pass in case an event was missed.

Authenticated rate limit is 5000 requests/hour on the REST API — generous enough for backfill + poll on any reasonably-sized repo.
