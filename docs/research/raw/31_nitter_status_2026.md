# Source: Nitter — project status (for llmwiki's Twitter/X subscription adapter)

- **URL:** https://github.com/zedeus/nitter
- **Fetched:** 2026-04-15
- **Purpose:** Verify what the realistic options are for following Twitter/X accounts as a subscription source.

---

## Status (extracted from the GitHub repo page)

- **Maintained**, 12.8k stars, active PRs (23 open at fetch time).
- **RSS feeds:** still listed as a supported feature.
- **Critical operational change:** *"Running a Nitter instance now requires real accounts, since Twitter removed the previous methods."*
- The README still claims *"Uses Twitter's unofficial API (no developer account required)"* but this conflicts with the real-account requirement in practice.
- Session tokens must be generated from throwaway Twitter accounts; see the project wiki's "Creating session tokens" page.

## Implication for llmwiki

Nitter works, but it is **no longer zero-setup**. A user who wants to subscribe to Twitter accounts has to:

1. Run their own Nitter instance (on a VPS, in Docker, or locally).
2. Maintain one or more throwaway Twitter accounts to provide session tokens.
3. Handle rate limits, IP bans, and account suspensions themselves.

For llmwiki this means Twitter subscriptions are a **tier-3 operational choice**, not a default. We document the three realistic options honestly (self-hosted nitter, rsshub-style bridges, manual tweet save via fxtwitter) and flag Twitter as fragile. We do not pretend to deliver "follow anyone on Twitter" out of the box — the platform makes that impossible without significant user-side investment.
