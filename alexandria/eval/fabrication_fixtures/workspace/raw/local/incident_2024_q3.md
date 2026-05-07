# Incident Report — 2024-09-12 Outage

## Timeline

At 03:14 UTC the primary database failed to accept writes. By 03:22 UTC the on-call engineer Alice had paged the team.

## Root Cause

The disk filling up caused write stalls. Logs were not being rotated because of a misconfigured logrotate.

## Quotes

When asked about prevention, Bob said: We should automate logrotate verification across all production hosts.

Alice replied: Yes, but we should also alert on disk usage above 80 percent, not 95 percent.

## Action Items

The team committed to automating logrotate checks. The 80 percent threshold change is pending review.

## Status

Pending — awaiting approval from the SRE lead.
