"""Alexandria's internal agent loop.

Drives research by composing navigation primitives (guide, search, grep,
read, follow, why) the same way a connected MCP agent would — but runs
locally inside Alexandria for CLI queries and automated belief updates.

Uses the configured LLM provider (Claude Code SDK, Anthropic, OpenAI, etc.)
to reason over the primitives and produce grounded answers.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from alexandria.llm.base import CompletionRequest, CompletionResult, Message, ToolDefinition


# The tools the agent can call — mirrors the MCP surface
AGENT_TOOLS = [
    ToolDefinition(
        name="search",
        description="FTS5 keyword search across wiki documents. Returns titles, paths, and snippets.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="grep",
        description="Regex pattern search across raw and wiki files. For exact phrases, error codes, names.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
            },
            "required": ["pattern"],
        },
    ),
    ToolDefinition(
        name="read",
        description="Read the full content of a document by path.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Document path (e.g. wiki/concepts/transformers.md)"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="beliefs",
        description="List current beliefs in the knowledge base, optionally filtered by topic.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Filter by topic (optional)"},
            },
        },
    ),
    ToolDefinition(
        name="answer",
        description="Provide the final answer to the user's question. Call this when you have enough information.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The answer text with [Source: path] citations"},
                "sources": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"title": {"type": "string"}, "path": {"type": "string"}}},
                    "description": "List of sources cited",
                },
            },
            "required": ["text"],
        },
    ),
]

SYSTEM_PROMPT = """You are Alexandria's research agent. Your job is to answer the user's question by navigating the knowledge base using the available tools.

Workflow:
1. Use 'search' with relevant keywords to find documents
2. Use 'read' to read the most relevant documents
3. Use 'beliefs' to check what structured claims exist on the topic
4. Use 'grep' if you need exact phrases or specific terms
5. Call 'answer' with your findings, citing sources as [Source: path]

Rules:
- ALWAYS use the tools to find information — never make up answers
- Search with multiple different keywords to get broad coverage
- Read the actual documents before answering — don't rely on snippets alone
- If you can't find relevant information, say so honestly
- Cite every claim with [Source: path]"""


def run_agent_query(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    question: str,
    max_turns: int = 6,
) -> dict[str, Any] | None:
    """Run the agent loop to answer a question.

    Returns dict with: answer, sources, tool_calls. Returns None if no LLM.
    """
    from alexandria.core.llm_ingest import _get_provider
    provider = _get_provider()
    if provider is None:
        return None

    messages: list[Message] = [
        Message(role="user", content=[{"type": "text", "text": question}]),
    ]

    tool_log: list[dict[str, Any]] = []

    for turn in range(max_turns):
        request = CompletionRequest(
            model="",
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            tools=AGENT_TOOLS,
            messages=messages,
            max_output_tokens=4096,
            temperature=0.2,
        )

        result = provider.complete(request)

        # Check if the agent wants to use tools
        if result.stop_reason == "tool_use":
            # Process each tool call
            tool_results: list[dict[str, Any]] = []
            for tc in result.tool_calls:
                tool_name = tc.get("name", "")
                tool_input = tc.get("input", {})
                tool_id = tc.get("id", f"tool_{turn}")

                # Execute the tool
                tool_output = _execute_tool(
                    conn, workspace, workspace_path, tool_name, tool_input
                )
                tool_log.append({"tool": tool_name, "input": tool_input, "output_len": len(tool_output)})

                # Check if this is the 'answer' tool
                if tool_name == "answer":
                    return {
                        "answer": tool_input.get("text", ""),
                        "sources": tool_input.get("sources", []),
                        "tool_calls": tool_log,
                    }

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": tool_output[:10000],  # cap context size
                })

            # Add assistant message + tool results to conversation
            messages.append(Message(role="assistant", content=result.content))
            messages.append(Message(role="tool_result", content=tool_results))
        else:
            # Agent finished without calling 'answer' tool — use the text response
            return {
                "answer": result.text,
                "sources": [],
                "tool_calls": tool_log,
            }

    # Ran out of turns
    return {
        "answer": "I explored the knowledge base but couldn't find a complete answer within the search budget.",
        "sources": [],
        "tool_calls": tool_log,
    }


def _execute_tool(
    conn: sqlite3.Connection,
    workspace: str,
    workspace_path: Path,
    tool_name: str,
    tool_input: dict[str, Any],
) -> str:
    """Execute a single tool call and return the text result."""
    if tool_name == "search":
        return _tool_search(conn, workspace, tool_input.get("query", ""))

    if tool_name == "grep":
        return _tool_grep(workspace_path, tool_input.get("pattern", ""))

    if tool_name == "read":
        return _tool_read(workspace_path, tool_input.get("path", ""))

    if tool_name == "beliefs":
        return _tool_beliefs(conn, workspace, tool_input.get("topic"))

    return f"Unknown tool: {tool_name}"


def _tool_search(conn: sqlite3.Connection, workspace: str, query: str) -> str:
    """FTS5 search across documents."""
    try:
        rows = conn.execute(
            """SELECT documents.title, documents.path,
                      substr(documents.content, 1, 300) as snippet
            FROM documents_fts
            JOIN documents ON documents.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ? AND documents.workspace = ?
            ORDER BY rank LIMIT 10""",
            (query, workspace),
        ).fetchall()
        if not rows:
            return f"No documents found for: {query}"
        lines = [f"Found {len(rows)} document(s):"]
        for r in rows:
            lines.append(f"\n- {r['title']} ({r['path']})")
            lines.append(f"  {r['snippet'][:200]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Search error: {exc}"


def _tool_grep(workspace_path: Path, pattern: str) -> str:
    """Regex search across files."""
    import re
    results: list[str] = []
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"Invalid regex: {exc}"

    for layer in ("wiki", "raw"):
        layer_dir = workspace_path / layer
        if not layer_dir.exists():
            continue
        for f in sorted(layer_dir.rglob("*.md")):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8")
                matches = compiled.findall(content)
                if matches:
                    rel = str(f.relative_to(workspace_path))
                    results.append(f"{rel}: {len(matches)} match(es) — {matches[0][:100]}")
            except Exception:
                continue

    if not results:
        return f"No matches for pattern: {pattern}"
    return f"Found matches in {len(results)} file(s):\n" + "\n".join(results[:20])


def _tool_read(workspace_path: Path, path: str) -> str:
    """Read a document by path."""
    full = workspace_path / path
    if not full.exists():
        return f"File not found: {path}"
    if not full.resolve().is_relative_to(workspace_path.resolve()):
        return f"Path outside workspace: {path}"
    try:
        content = full.read_text(encoding="utf-8")
        if len(content) > 8000:
            return content[:8000] + "\n\n... (truncated, full document is longer)"
        return content
    except Exception as exc:
        return f"Error reading {path}: {exc}"


def _tool_beliefs(conn: sqlite3.Connection, workspace: str, topic: str | None = None) -> str:
    """List current beliefs."""
    try:
        if topic:
            rows = conn.execute(
                """SELECT statement, topic, wiki_document_path, subject, predicate, object
                FROM wiki_beliefs WHERE workspace = ? AND topic LIKE ?
                AND superseded_at IS NULL LIMIT 20""",
                (workspace, f"%{topic}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT statement, topic, wiki_document_path, subject, predicate, object
                FROM wiki_beliefs WHERE workspace = ? AND superseded_at IS NULL LIMIT 20""",
                (workspace,),
            ).fetchall()

        if not rows:
            return f"No beliefs found{f' for topic: {topic}' if topic else ''}."
        lines = [f"Found {len(rows)} belief(s):"]
        for r in rows:
            lines.append(f"\n- {r['statement']}")
            lines.append(f"  topic: {r['topic']} | source: {r['wiki_document_path']}")
            if r["subject"]:
                lines.append(f"  structured: {r['subject']} {r['predicate']} {r['object']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Belief query error: {exc}"
