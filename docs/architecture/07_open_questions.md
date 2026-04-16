# 07 — Open Questions

Decisions deferred until we have code or user feedback to choose. Don't resolve speculatively.

## A. Where does the agent loop actually run? — DECIDED

**Resolved in `11_inference_endpoint.md`.** Two modes, both MVP:

1. **Client MCP** — the only interactive mode. Claude Code / Claude.ai / Cursor / Codex / Claude Desktop / Windsurf / Zed / Continue. Zero LLM config on llmwiki's side. The client owns inference, manages context, renders streaming output, takes user input. llmwiki just exposes tools. This handles all user-facing work.
2. **Daemon-owned** — the only mode where llmwiki itself calls an LLM. Scheduled temporal synthesis (`10_event_streams.md`), scheduled lint, and CLI batch operations (`llmwiki synthesize`, `llmwiki lint --run`). Opt-in per workspace, bounded token budgets, dry-run preview, mandatory cost telemetry, pluggable provider (Anthropic, OpenAI, Gemini, or any OpenAI-compatible endpoint — Ollama, vLLM, SGLang, LM Studio, llama.cpp server, TGI, LiteLLM proxy).

**`llmwiki chat` is explicitly not built.** llmwiki is a knowledge engine; it does not replicate the interactive chat experience that every MCP client already provides well.

Both modes share the same tool surface (`04_guardian_agent.md`), workspace boundaries, and data model. The user's choice between Claude API, ChatGPT API, Gemini API, or a self-hosted stack (vLLM / SGLang / Ollama) is a per-preset configuration in `~/.llmwiki/config.toml` — **but only for the daemon-owned mode.** Interactive work in Claude Code uses Claude Code's own inference config; llmwiki is indifferent to it.

## B. Auto-ingest for subscriptions

Subscriptions deliver items every hour. Should the agent auto-ingest them, or wait for the user to ask?

- **Wait for user.** Default. Subscription items sit in the queue until the user says "ingest the new items." Preserves intent, bounds tokens.
- **Auto-ingest per workspace opt-in.** `llmwiki automation create --workspace X --on subscription --run ingest`. The daemon runs a headless ingest against a local model or a configured provider key. Requires careful token budgeting and a failure-mode policy.

**Leaning:** ship wait-for-user at MVP. Automations are a v2 hook.

## C. Cross-workspace queries

"What do I know about OAuth across all my projects?" — legitimate, useful, complicated.

Options:
1. **No.** Per-workspace only at MVP. Users open multiple sessions and synthesize manually.
2. **Meta-workspace.** A special `meta` workspace that holds summaries from every other workspace's `overview.md` and `index.md`. Lint keeps it fresh. Queries hit meta first, then drill into the source workspace.
3. **Federated MCP tool.** A `search_all_workspaces(query)` tool that hits every workspace's FTS5 index. No agent cross-writes — results return as a list of `(workspace, page, snippet)` tuples the user picks from.

**Leaning:** option 3 first (read-only). Option 2 if option 3 produces noisy answers.

## D. How does the agent know what it should update? — DECIDED

**Resolved in `15_cascade_and_convergence.md`.** The cascade workflow is now formalized: phase 1 reads claims, phase 2 grep-locates affected pages, phase 3 stages writes, phase 4 plans index/overview updates, phase 5 hands off to the verifier. The convergence policy is hedge-with-dated-marker — never silent overwrite. M2 (cascade coverage) in `14_evaluation_scaffold.md` measures whether the cascade actually touched every page it should have, and blocks new ingests if M2 falls below 0.70.

## D-original. How does the agent know what it should update? (original framing, kept for context)

User says *"A new RFC landed for Acme. Update any docs that are affected."* The self-awareness story relies on `wiki_log_entries` + `wiki_claim_provenance` catching every citation. But:

- What if the agent wrote something without a footnote? (Shouldn't happen — `write` rejects it — but lint might find legacy content.)
- What if the "affected" claim spans multiple pages and the provenance table only records one?

**Leaning:** accept imperfect recall. `lint` already flags stale citations via superseded raw documents. The agent should run `lint` as part of every ingest on existing workspaces to catch the holes.

## E.1 Capability floor — DECIDED

**Resolved in `14_evaluation_scaffold.md`.** `llmwiki eval floor --preset <preset>` runs M1 + M2 against a fixed 10-source test set and publishes a numeric score per preset. Daemon startup warns when the configured preset is at or below the floor. Closes ai-engineer R8.

## E. Code sources — ingest level

For a GitHub repo, how deep does ingest go?

- **Docs only** — `README`, `docs/`, `*.md`, `CHANGELOG`. Safe default. High signal.
- **Docs + API surface** — plus extracted signatures from the public API. Needs language-specific parsers.
- **Full code** — every file. Blows up token budgets. Only useful for tiny repos.

**Leaning:** docs-only at MVP. Add "API surface extraction" via tree-sitter for top languages as an opt-in flag per-adapter.

## F. Export formats

`llmwiki export --workspace X` should produce what?

1. **Raw markdown directory** — default. Bit-for-bit copy.
2. **Obsidian-compatible zip** — same files, plus an `.obsidian/` config seeded for the topic layout.
3. **HTML site** — static site generator output (via mkdocs or mdbook) for sharing.
4. **JSON dump** — everything, including SQLite metadata, for migration between machines.

**Leaning:** ship 1 and 4 at MVP (simple). 2 and 3 are easy follow-ups.

## Adaptive routing — decided and declined

The gist at `research/raw/26_*` calls adaptive routing (*"simple factoid → direct LLM answer; moderate → hybrid retrieval; complex → graph/multi-agent"*) *"mandatory for production cost control in 2026."* We decline to build it. Rationale: **the agent is already the router.** With agentic navigation, the guardian naturally varies effort with query complexity — a trivial factoid becomes one `read`, a multi-hop question becomes multiple `follow` calls plus possibly a subagent. A separate routing layer would add latency, a policy to maintain, and a failure mode we don't have today. If the user reports that the agent consistently over-reads on simple questions, the fix is a sharper `guide()` instruction, not a new router component.

## G. Retrieval is agentic — vectors are explicitly out of scope

**Decided.** No embedding pipeline, no vector store, ever. The agent is the retriever; our job is to expose good navigation primitives (`guide`, `list`, `grep`, `search`, `read`, `follow`) and subagent re-entrancy. This is grounded in Karpathy's own tweet and Anthropic's multi-agent research post (see `research/reference/12_agentic_retrieval.md`).

When a workspace grows past the point where the agent can navigate it comfortably, the fixes are:
1. Better orientation documents — the `lint` pass produces topic-level overview pages so the agent reads summaries before drilling in.
2. Smarter subagent patterns — one subagent per topic, each with its own context window, each returning a condensed summary.
3. Sharper primitives — if `grep` isn't enough, add `ast-grep` or a structural tool; we do not add vectors.

If a user reports "the agent can't find the right page on a 1000-page workspace," the investigation is: what orientation docs is it reading, why didn't the index point it at the right topic, and would a subagent pattern have caught this. Not: should we add pgvector.

## H. Backup, restore, and portability

The whole data directory is portable by design — copy it, git it, syncthing it. But:
- What about credentials in `secrets/`? They're encrypted with an OS-keyring-derived key, which is machine-specific. Restore on a new machine requires a passphrase fallback.
- What about SQLite? It's rebuildable via `llmwiki reindex`, so restore is just "copy files + reindex."

**Leaning:** document the happy-path recipe. `llmwiki backup create` and `llmwiki backup restore` as thin wrappers over tar + reindex.

## I. Multiple machines, same workspaces

User wants the same `~/.llmwiki/` on laptop and desktop. Three options:

1. **Syncthing/Dropbox/git the whole directory.** Works for files; SQLite can corrupt on concurrent writes. Solution: the daemon runs on only one machine at a time (enforced by a lock file), the other is read-only.
2. **Don't support it.** Single machine, period.
3. **Build a sync mode** where both machines write to a git remote and we resolve conflicts on pull. Out of scope for MVP.

**Leaning:** document option 1 as "use at your own risk" and rely on lock files. Don't build anything.

## J. Subscriptions to email newsletters — the UX problem

IMAP works but configuring it (app passwords, OAuth per provider) is painful. Alternatives:

1. **Unique inbound email** (like Kindle's send-to-email) — we provide an address, user forwards newsletters to it, we pick them up. Needs us to run an SMTP relay. Not single-user-friendly.
2. **Local mbox monitoring** — user points us at `~/.local/share/mail/<folder>/` if they use a real mail client. Works for Mu4e/Notmuch users, useless for Gmail-only users.
3. **Gmail/Fastmail API adapters** — OAuth + provider-specific code per mail host.

**Leaning:** ship IMAP + app-password at MVP (ugly but works). Add Gmail API as a follow-up. Document the "filter to a dedicated label + IMAP" recipe.

---

When any of these questions gets answered, it becomes a new numbered doc or an edit to an existing one. Until then, they live here so we don't re-litigate them.
