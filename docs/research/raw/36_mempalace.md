# Source: MemPalace (local-first AI memory, parallel project)

- **URL:** https://github.com/mempalace/mempalace
- **Official site:** https://mempalaceofficial.com (per the repo's explicit scam warning — `mempalace.tech` is an impostor)
- **PyPI:** https://pypi.org/project/mempalace/
- **License:** MIT
- **Version at fetch:** 3.3.0 (README shield); v4.0.0-alpha planned per ROADMAP
- **Authors:** Milla Jovovich (creator, per MISSION.md), @bensig (engineering co-founder)
- **Local clone:** /tmp/mempalace
- **Fetched:** 2026-04-16
- **Purpose:** a parallel local-first personal AI memory system. Worth deep reading because it is a sibling, not a competitor, and several of its design choices directly inform llmwiki even though we diverge on the load-bearing retrieval question.

This file preserves the load-bearing excerpts verbatim so future architecture decisions can cite the primary material.

---

## README tagline (verbatim)

> "Local-first AI memory. Verbatim storage, pluggable backend, 96.6% R@5 raw on LongMemEval — zero API calls."

## What it is (verbatim, README)

> "MemPalace stores your conversation history as verbatim text and retrieves it with semantic search. It does not summarize, extract, or paraphrase. The index is structured — people and projects become *wings*, topics become *rooms*, and original content lives in *drawers* — so searches can be scoped rather than run against a flat corpus."

> "The retrieval layer is pluggable. The current default is ChromaDB; the interface is defined in `mempalace/backends/base.py` and alternative backends can be dropped in without touching the rest of the system."

> "Nothing leaves your machine unless you opt in."

## Mission quotes (verbatim, MISSION.md)

> "I wanted to create a system with the ability to really remember everything AND be able to find it quickly, easily and also be able to remember things when I didn't. THAT in itself felt like something so important. Like 'remember when we talked about that idea…' but in vague terms. Impossible with regular keyword search tools."

> "So MemPalace is not just about storing info in a highly structured way. But also RETRIEVING it in a highly UNSTRUCTURED way lol!"

> "I was inspired by the Zettelkasten method (created by German sociologist Niklas Luhmann) — his idea of small cross-referenced index cards that point to each other. That's the architecture behind the palace: wings, rooms, closets, and drawers, all connected so you can find things from any angle, not just the one you filed them under."

> "So this version now has taken all the noise out of the chat window and all that work is done by a subagent in the background while you can continue working knowing that all your conversation is being saved VERBATIM in the background."

## The charter (verbatim, CLAUDE.md)

> "Memory is identity. When an AI forgets everything between conversations, it cannot build real understanding — of you, your work, your people, your life."

> "MemPalace exists to solve this. It is a memory system — not a search engine, not a RAG pipeline, not a vector database wrapper. It treats every word you have shared as sacred, stores it verbatim, and makes it instantly available. Your data never leaves your machine. We never summarize. We never paraphrase. We return your exact words."

> "100% recall is the design requirement — the target every search path is measured against. Anything less means forgetting, and forgetting means starting over."

## Design principles (verbatim, CLAUDE.md)

> - "**Verbatim always** — Never summarize, paraphrase, or lossy-compress user data. The system searches the index and returns the original words. If a user said it, we store exactly what they said. This is the foundational promise."
> - "**Incremental only** — Append-only ingest after initial build. Never destroy existing data to rebuild. A crash mid-operation must leave the existing palace untouched."
> - "**Entity-first** — Everything is keyed by real names with disambiguation by DOB, ID, or context. People matter more than topics."
> - "**Local-first, zero API** — All extraction, chunking, and embedding happens on the user's machine. No cloud dependency for memory operations. No API keys required."
> - "**Performance budgets** — Hooks under 500ms. Startup injection under 100ms. Memory should feel instant."
> - "**Privacy by architecture** — The system physically cannot send your data because it never leaves your machine. No telemetry, no phone-home, no external service dependencies for core operations."
> - "**Background everything** — Filing, indexing, timestamps, and pipeline work happen via hooks in the background. Nothing interrupts the user's conversation. Zero tokens spent on bookkeeping in the chat window."

## The palace structure (verbatim, concepts/the-palace.md)

```
WING (person/project)
  └── ROOM (day/topic)
        └── DRAWER (verbatim text chunk)
```

- **Wings** — "A person or project. As many as you need."
- **Rooms** — "Specific topics within a wing. Examples: `auth-migration`, `graphql-switch`, `ci-pipeline`."
- **Halls** — conceptual categories within a wing: `hall_facts` (decisions), `hall_events` (sessions/milestones/debugging), `hall_discoveries`, `hall_preferences`, `hall_advice`.
- **Tunnels** — "Connections *between* wings. When the same room appears in different wings, the graph layer can treat that as a cross-wing connection."
- **Closets** — "compact notes that point back to the original content. In the current implementation, the main persisted storage path is still the underlying drawer text plus metadata."
- **Drawers** — "The original stored text chunks. This is the primary retrieval layer used by the current search and benchmark flows."

## The 4-layer memory stack (verbatim, concepts/memory-stack.md)

| Layer | What | Size | When |
|---|---|---|---|
| **L0** | Identity — who is this AI? | ~50-100 tokens | Always loaded |
| **L1** | Essential Story — top moments | ~500-800 tokens | Always loaded |
| **L2** | Room Recall — filtered retrieval | ~200–500 each | When topic comes up |
| **L3** | Deep Search — full semantic query | Variable | When explicitly asked |

> "In the current implementation, a typical wake-up is roughly **~600-900 tokens** for L0 + L1. Searches only fire when needed."

L0 is a plain text file at `~/.mempalace/identity.txt`. L1 is auto-generated from the top-importance drawers (scored by `importance` / `emotional_weight` / `weight` metadata fields), grouped by room, truncated to ~3200 chars (`MAX_DRAWERS=15`, `MAX_CHARS=3200`, `MAX_SCAN=2000`). L2 is wing/room-filtered retrieval from ChromaDB. L3 is full semantic search.

## Layer 1 code excerpt (from `/tmp/mempalace/mempalace/layers.py`)

```python
class Layer1:
    """
    ~500-800 tokens. Always loaded.
    Auto-generated from the highest-weight / most-recent drawers in the palace.
    Groups by room, picks the top N moments, compresses to a compact summary.
    """

    MAX_DRAWERS = 15   # at most 15 moments in wake-up
    MAX_CHARS = 3200   # hard cap on total L1 text (~800 tokens)
    MAX_SCAN = 2000    # don't scan more than this for L1 generation
```

The `MemoryStack` class exposes `wake_up(wing=None)` (L0+L1), `recall(wing, room)` (L2), and `search(query, wing, room)` (L3).

## Benchmark results (verbatim, README)

**LongMemEval — retrieval recall (R@5, 500 questions):**

| Mode | R@5 | LLM required |
|---|---|---|
| Raw (semantic search, no heuristics, no LLM) | **96.6%** | None |
| Hybrid v4, held-out 450q (tuned on 50 dev, not seen during training) | **98.4%** | None |
| Hybrid v4 + LLM rerank (full 500) | ≥99% | Any capable model |

**Other benchmarks:**

| Benchmark | Metric | Score |
|---|---|---|
| LoCoMo (session, top-10, no rerank) | R@10 | 60.3% |
| LoCoMo (hybrid v5, top-10, no rerank) | R@10 | 88.9% |
| ConvoMem (all categories, 250 items) | Avg recall | 92.9% |
| MemBench (ACL 2025, 8,500 items) | R@5 | 80.3% |

> "The raw 96.6% requires no API key, no cloud, and no LLM at any stage."

## Knowledge graph (verbatim, concepts/knowledge-graph.md)

> "MemPalace includes a temporal entity-relationship graph — like Zep's Graphiti, but SQLite instead of Neo4j. Local and free."

> "Entity-relationship triples with temporal validity: `Subject → Predicate → Object [valid_from → valid_to]`. Facts have time windows. When something stops being true, you invalidate it — and historical queries still find it."

SQLite schema:
- `entities` — id (lowercase normalized name), name, type (person/project/tool/concept), properties (JSON)
- `triples` — subject → predicate → object, valid_from, valid_to (NULL = still current), confidence, source_closet (link back to verbatim memory)

## Contradiction detection (verbatim, concepts/contradiction-detection.md)

Flagged as **experimental / planned**, not yet a shipped end-to-end feature. Example categories:

> "Input:  'Soren finished the auth migration'
>  Output: 🔴 AUTH-MIGRATION: attribution conflict — Maya was assigned, not Soren"
>
> "Input:  'Kai has been here 2 years'
>  Output: 🟡 KAI: wrong_tenure — records show 3 years (started 2023-04)"
>
> "Input:  'The sprint ends Friday'
>  Output: 🟡 SPRINT: stale_date — current sprint ends Thursday (updated 2 days ago)"

Three categories: **attribution conflicts** (wrong person credited), **temporal errors** (wrong dates/tenures), **stale information** (facts superseded).

## Auto-save hooks (verbatim, guide/hooks.md)

Two hooks for Claude Code and Codex:

| Hook | When It Fires | What Happens |
|---|---|---|
| **Save Hook** | Every 15 human messages | Blocks the AI, tells it to save key topics/decisions/quotes to the palace |
| **PreCompact Hook** | Right before context compaction | Emergency save — forces the AI to save everything before losing context |

Install config (Claude Code) — verbatim:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_save_hook.sh",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh",
        "timeout": 30
      }]
    }]
  }
}
```

Install config (Codex CLI):

```json
{
  "Stop": [{
    "type": "command",
    "command": "/absolute/path/to/hooks/mempal_save_hook.sh",
    "timeout": 30
  }],
  "PreCompact": [{
    "type": "command",
    "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh",
    "timeout": 30
  }]
}
```

The `stop_hook_active` flag prevents infinite loops (hook fires → AI saves → AI tries to stop again → second fire sees the flag and lets it through).

> "**Zero extra tokens.** The hooks are bash scripts that run locally. They don't call any API. The only 'cost' is a few seconds of the AI organizing memories at each checkpoint."

## Save hook implementation summary (`/tmp/mempalace/hooks/mempal_save_hook.sh`)

- Default `SAVE_INTERVAL=15` — save every 15 human messages.
- Reads Claude Code's JSON input from stdin: `session_id`, `stop_hook_active`, `transcript_path`.
- Counts human messages in the JSONL transcript (filters out `<command-message>` wrapped entries).
- Tracks last save point per session in `~/.mempalace/hook_state/<session_id>_last_save`.
- When threshold is hit, optionally runs `mempalace mine <transcript_dir>` in the background and emits a JSON decision that **blocks** the AI with a `reason` instructing it to save session state to the palace.
- `MEMPAL_VERBOSE=true` → developer mode (block and surface to chat). Default silent mode → returns `{}` so no blocking; background mine only.

## Mining conversations (verbatim, guide/mining.md)

> "Indexes conversation exports from Claude, ChatGPT, Slack, and other tools. Chunks by exchange pair (human + assistant turns)."

```bash
mempalace mine ~/chats/ --mode convos
```

> "Supports five chat formats automatically:
> - Claude JSON exports
> - ChatGPT exports
> - Slack exports
> - Markdown conversations
> - Plain text transcripts"

Exchange-pair chunking from `/tmp/mempalace/mempalace/convo_miner.py`:

```python
MIN_CHUNK_SIZE = 30
CHUNK_SIZE = 800          # chars per drawer
MAX_FILE_SIZE = 10 * 1024 * 1024   # 10 MB — skip larger files

def chunk_exchanges(content: str) -> list:
    """
    Chunk by exchange pair: one > turn + AI response = one unit.
    Falls back to paragraph chunking if no > markers.
    """
```

`mempalace split` splits concatenated "mega-files" (multiple sessions in one file) before mining.

## Claude Code plugin install (verbatim, guide/claude-code.md)

```bash
claude plugin marketplace add MemPalace/mempalace
claude plugin install --scope user mempalace
```

> "With the plugin installed, Claude Code automatically:
> - Starts the MemPalace MCP server on launch
> - Has access to all 19 tools [n.b. — the mcp-tools reference lists ~29 tools; the doc is inconsistent]
> - Learns the AAAK dialect and memory protocol from the `mempalace_status` response
> - Searches the palace before answering questions about past work"

## AAAK dialect (verbatim, concepts/aaak-dialect.md)

**Explicitly experimental, not the default**:

> "AAAK is an experimental lossy abbreviation system... It is readable by any LLM — Claude, GPT, Gemini, Llama, Mistral — without a decoder."

> "**Experimental**: AAAK is a separate compression layer, **not the storage default**. The 96.6% benchmark score comes from raw verbatim mode. AAAK mode currently scores 84.2% R@5 — a 12.4 point regression. We're iterating."

Format: `Header: FILE_NUM|PRIMARY_ENTITY|DATE|TITLE` / `Zettel: ZID:ENTITIES|topic_keywords|"key_quote"|WEIGHT|EMOTIONS|FLAGS`. Entity codes are three-letter uppercase (`ALC=Alice`). Emotions and flags drawn from fixed vocabularies.

## What mempalace explicitly refuses (verbatim, CLAUDE.md)

> "We do not accept summarization of user content, cloud storage/sync features, telemetry or analytics, features requiring API keys for core memory, or shortcuts that bypass verbatim storage."

## Top-level repo layout

```
mempalace/
├── MISSION.md                # Creator's story — why this exists
├── CLAUDE.md                 # Charter for LLMs working on the codebase
├── ROADMAP.md                # v3.1.1 stability → v4.0.0-alpha (pluggable backends, local NLP, hybrid search)
├── benchmarks/               # BENCHMARKS.md + reproducible harness
├── docs/                     # Additional documentation
├── hooks/                    # mempal_save_hook.sh, mempal_precompact_hook.sh
├── integrations/openclaw/    # OpenClaw (ClawHub agents) MCP integration
├── mempalace/                # Python package
│   ├── mcp_server.py         # 29 MCP tools (palace CRUD, knowledge graph, navigation, agent diaries, system)
│   ├── cli.py
│   ├── miner.py              # Project file miner
│   ├── convo_miner.py        # Conversation transcript miner (5 formats)
│   ├── searcher.py           # Hybrid BM25 + vector
│   ├── knowledge_graph.py    # Temporal ER graph (SQLite)
│   ├── palace.py             # Shared palace operations
│   ├── palace_graph.py       # Room traversal + cross-wing tunnels
│   ├── backends/             # Pluggable storage (ChromaDB default, PostgreSQL / LanceDB / PalaceStore in v4)
│   ├── dialect.py            # AAAK compression
│   ├── entity_detector.py    # Auto-detect people/projects
│   ├── entity_registry.py    # Entity storage and disambiguation
│   ├── layers.py             # L0-L3 MemoryStack (493 lines)
│   ├── fact_checker.py
│   ├── diary_ingest.py
│   ├── general_extractor.py  # Decisions, preferences, milestones, problems, emotional-context
│   └── ...
└── website/                  # Docs site (guide + concepts + reference)
```

## 29-tool MCP surface (summary from `website/reference/mcp-tools.md`)

Groups:
- **Palace read**: `status`, `list_wings`, `list_rooms`, `get_taxonomy`, `search`, `check_duplicate`, `get_aaak_spec`
- **Palace write**: `add_drawer`, `delete_drawer`, `get_drawer`, `list_drawers`, `update_drawer`
- **Knowledge graph**: `kg_query`, `kg_add`, `kg_invalidate`, `kg_timeline`, `kg_stats`
- **Navigation**: `traverse`, `find_tunnels`, `graph_stats`, `create_tunnel`, `list_tunnels`, `delete_tunnel`, `follow_tunnels`
- **Agent diaries**: `diary_write`, `diary_read`
- **System**: `hook_settings`, `memories_filed_away`, `reconnect`

Every tool is read-only from the agent's perspective or a single-purpose write (one drawer, one tunnel, one diary entry). No batch mutations.

## Roadmap highlights (verbatim, ROADMAP.md)

v4.0.0-alpha (planned this week per ROADMAP):

- **Swappable storage**: PostgreSQL backend (with `pg_sorted_heap`), LanceDB backend (multi-device sync), PalaceStore bespoke store. ChromaDB remains default.
- **Local NLP**: entity extraction, relationship detection, topic classification without external API calls. Feature-flagged.
- **Hybrid search**: keyword text-match fallback when vector similarity misses exact terms.
- **Stale index detection**: automatic reconnection when HNSW index changes on disk.
- **Time-decay scoring**: recent memories surface before older ones.
- **Query sanitization**: prompt-contamination mitigation.

Branches: `main` (tagged releases) ← `develop` (active) ← PRs.

## License and credits

MIT. Authors: Milla Jovovich (creator), @bensig (engineering). Scam warning in the README calls out `mempalace.tech` as an impostor domain; only `mempalaceofficial.com` + the GitHub org + the PyPI package are canonical.
