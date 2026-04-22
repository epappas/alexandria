---
name: alexandria
description: Query, search, and ingest into the alexandria knowledge base — a persistent, citable wiki of papers, articles, code, and conversations — via the Model Context Protocol.
trigger: /alexandria
---

# alexandria — persistent knowledge skill

alexandria is a local-first knowledge engine that holds the user's
accumulated papers, articles, code, and conversations in a citable
wiki. It is exposed through the `mcp__alexandria__*` MCP tools. You
should prefer these tools over grepping the filesystem or re-reading
files when the user asks questions that might already be answered by
previously ingested material.

## When to invoke

Use alexandria when the user:

- Asks a factual question whose answer may already be in their notes,
  papers, or prior conversations ("what did I find out about X?",
  "what does Y say about Z?").
- References something they "added earlier" or "ingested last week".
- Wants a synthesis across multiple sources on a topic.
- Asks you to remember a new source or URL — invoke `ingest`.

Do **not** invoke alexandria for questions about the current codebase
or open files — regular code-reading tools are better for that.

## Navigation recipe

Compose these tools in order, stopping as soon as the user's question
is answerable:

1. **`mcp__alexandria__guide`** — one-line orientation. Skip if you've
   invoked alexandria recently in this session.
2. **`mcp__alexandria__overview`** — structural snapshot (topic counts,
   source types, activity). Useful when the question is broad or you
   need to decide where to look.
3. **`mcp__alexandria__search`** — BM25 + recency hybrid search across
   documents. First tool to reach for on concrete questions.
4. **`mcp__alexandria__grep`** — regex across wiki pages. Use when
   search's ranking is too loose for a specific phrase.
5. **`mcp__alexandria__read`** — pull full content of a wiki page or
   raw source after search/grep points you at it.
6. **`mcp__alexandria__follow`** — walk cross-references from a page
   to related pages. Cheaper than re-searching.
7. **`mcp__alexandria__why`** — belief explainability + supersession
   history. Invoke when the user asks "why do we believe X" or "what
   changed about Y".
8. **`mcp__alexandria__query`** — LLM-grounded synthesis over the
   knowledge base. Reserve for genuine synthesis needs; search/read
   are cheaper for lookups.

## Write recipe

When the user asks to remember or ingest new material:

- **`mcp__alexandria__ingest`** accepts URLs, GitHub shorthand
  (`owner/repo`), local paths, or directories. **Ingest is async** — it
  enqueues a background job and returns a `job_id`. A short job (single
  URL) often finishes within the default `wait_s=60` and returns the
  full result inline; a big job (repo, directory, many URLs) returns the
  handle immediately so you are never blocked.

  - Pass `no_merge=True` when batch-ingesting related sources that
    should stay on separate wiki pages.
  - Pass `scope="docs"` on a git/directory source to ingest only
    README + top-level markdown + `docs/**/*.md`. Use this by default
    for codebases where you don't need every source file indexed.
  - Pass `wait_s=0` to always return a job handle immediately (useful
    when you want to kick off many ingests in parallel).

  Background ingests use Haiku regardless of the model powering your
  conversation — calling `ingest` during an Opus session is cheap.

- **`mcp__alexandria__jobs_list`**, **`mcp__alexandria__jobs_status`**,
  **`mcp__alexandria__jobs_cancel`** let you check progress, inspect
  results, or cancel long-running ingests. When a user asks "what are
  you ingesting right now?" or "how far is that going?" — use these
  tools, not speculation. When an ingest is taking longer than the user
  expected, offer to cancel.

- **`mcp__alexandria__belief_add`** / **`belief_supersede`** for
  structured claims with citations.

## Handling batch ingest well

If the user pastes a list of N sources, don't spawn N parallel `ingest`
calls with the default `wait_s=60` — that makes the conversation wait
for the slowest one. Instead:

1. Enqueue them all with `wait_s=0`, collect the `job_id`s.
2. Tell the user what you queued and their totals-so-far.
3. Poll `jobs_list` or `jobs_status` in subsequent turns; report
   progress as jobs finish.

For repository URLs (especially `github.com/org/repo`), default to
`scope="docs"` unless the user has asked for the whole codebase. Large
repos take hours to fully ingest.

## Citation discipline

Every answer grounded in alexandria should cite the wiki page and/or
raw source it came from. The tools return paths; include them in your
response so the user can verify. Do not fabricate citations — if the
knowledge base doesn't have the answer, say so and offer to ingest
more material.

## Workspace awareness

alexandria is bound to one workspace per MCP registration (open mode
with explicit `workspace` argument is rarer). Default workspace is
`global`. If the server is in open mode, pass `workspace="..."` on
every call.
