# Source: Slack — free plan message history policy

- **URL:** https://slack.com/help/articles/7050776459923-Slack-Free-plan-updates
- **Fetched:** 2026-04-15
- **Purpose:** determine what historical Slack content alexandria can actually access on a free workspace.

---

## Finding (verbatim / extracted)

> "Messages and files on the Free plan will only be stored for one year. Any content in your workspace more than a year old will be permanently deleted."

Plus a secondary constraint in the plan-comparison table: **90-day access** to message and file history on the Free plan (searchable/accessible through the standard interface).

Paid tiers (Pro, Business+, Enterprise+) remove both restrictions.

## Implication for alexandria

1. **90-day access** means the Slack API's `conversations.history` will return roughly the last 90 days on a free workspace. Older messages are still present (up to 1 year) but inaccessible via search/scroll.
2. **1-year deletion** is a hard wall — content older than a year is physically gone from Slack's servers.
3. **alexandria can only ingest Slack history it captures while it is running.** Day-1 install → we see everything from day 1 forward. Retroactive ingest of a multi-year project's Slack history on a free workspace is impossible.

Architectural consequences:
- Configure the Slack adapter to poll aggressively early in a workspace's life to capture the 90-day window before it rolls off.
- Store captured messages in our local SQLite event table indefinitely, independent of Slack's own retention.
- Document the constraint to users with a free-tier workspace so they can upgrade or accept partial history.
- Paid workspaces are unconstrained — alexandria can pull full history on setup.
