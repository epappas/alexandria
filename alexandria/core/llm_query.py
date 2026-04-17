"""LLM-powered query — understands natural language questions.

1. Extracts search keywords from the question using the LLM
2. Searches across all knowledge sources using those keywords
3. Sends the retrieved context + original question to the LLM
4. Returns a grounded answer with citations to sources
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from alexandria.llm.base import CompletionRequest, CompletionResult, Message


KEYWORD_PROMPT = """Extract 3-5 search keywords from this question. Return ONLY a JSON array of strings, nothing else.

Question: {question}"""

ANSWER_PROMPT = """You are a knowledge assistant. Answer the user's question using ONLY the provided context.
If the context doesn't contain enough information, say so honestly.
Cite your sources using [Source: title] format.

Context:
{context}

Question: {question}

Answer concisely and factually, citing sources."""


def llm_query(
    conn: sqlite3.Connection,
    workspace: str,
    question: str,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Answer a question using LLM-powered retrieval and synthesis.

    Returns dict with: answer, sources, keywords. Returns None if no LLM available.
    """
    from alexandria.core.llm_ingest import _get_provider
    provider = _get_provider()
    if provider is None:
        return None

    # Step 1: Extract search keywords from the question
    keywords = _extract_keywords(provider, question)
    if not keywords:
        keywords = question.split()[:5]

    # Step 2: Search with each keyword and merge results
    all_docs: list[dict] = []
    all_beliefs: list[dict] = []
    seen_paths: set[str] = set()

    for kw in keywords:
        docs = _fts_search_documents(conn, workspace, kw, limit)
        for d in docs:
            if d["path"] not in seen_paths:
                seen_paths.add(d["path"])
                all_docs.append(d)

        beliefs = _fts_search_beliefs(conn, workspace, kw, limit)
        all_beliefs.extend(beliefs)

    # Step 3: Build context from retrieved results
    context = _build_context(all_docs[:limit], all_beliefs[:limit])

    if not context.strip():
        return {"answer": "No relevant information found in the knowledge base.", "sources": [], "keywords": keywords}

    # Step 4: Ask the LLM to answer using the context
    answer = _generate_answer(provider, question, context)

    return {
        "answer": answer,
        "sources": [{"title": d["title"], "path": d["path"]} for d in all_docs[:limit]],
        "beliefs": [{"statement": b["statement"], "topic": b["topic"]} for b in all_beliefs[:limit]],
        "keywords": keywords,
    }


def _extract_keywords(provider: Any, question: str) -> list[str]:
    """Use the LLM to extract search keywords from a natural language question."""
    request = CompletionRequest(
        model="",
        system=[],
        tools=[],
        messages=[
            Message(role="user", content=[{"type": "text", "text": KEYWORD_PROMPT.format(question=question)}]),
        ],
        max_output_tokens=100,
        temperature=0.0,
    )
    try:
        result = provider.complete(request)
        text = result.text.strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.split("\n") if not l.startswith("```"))
        keywords = json.loads(text)
        if isinstance(keywords, list):
            return [str(k) for k in keywords[:5]]
    except Exception:
        pass
    return []


def _generate_answer(provider: Any, question: str, context: str) -> str:
    """Use the LLM to synthesize an answer from retrieved context."""
    request = CompletionRequest(
        model="",
        system=[],
        tools=[],
        messages=[
            Message(role="user", content=[{
                "type": "text",
                "text": ANSWER_PROMPT.format(question=question, context=context[:30_000]),
            }]),
        ],
        max_output_tokens=2048,
        temperature=0.2,
    )
    try:
        result = provider.complete(request)
        return result.text.strip()
    except Exception as exc:
        return f"Error generating answer: {exc}"


def _build_context(docs: list[dict], beliefs: list[dict]) -> str:
    """Build a context string from retrieved documents and beliefs."""
    parts: list[str] = []

    for doc in docs:
        content = doc.get("content", "")[:3000]
        parts.append(f"--- Source: {doc['title']} ({doc['path']}) ---\n{content}")

    if beliefs:
        belief_text = "\n".join(f"- {b['statement']} [topic: {b['topic']}]" for b in beliefs)
        parts.append(f"--- Beliefs ---\n{belief_text}")

    return "\n\n".join(parts)


def _fts_search_documents(conn: sqlite3.Connection, workspace: str, keyword: str, limit: int) -> list[dict]:
    """FTS search on documents, returning full content for context building."""
    try:
        rows = conn.execute(
            """SELECT documents.title, documents.path, documents.content
            FROM documents_fts
            JOIN documents ON documents.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ? AND documents.workspace = ?
            ORDER BY rank LIMIT ?""",
            (keyword, workspace, limit),
        ).fetchall()
        return [{"title": r["title"], "path": r["path"], "content": r["content"] or ""} for r in rows]
    except Exception:
        return []


def _fts_search_beliefs(conn: sqlite3.Connection, workspace: str, keyword: str, limit: int) -> list[dict]:
    """FTS search on beliefs."""
    try:
        rows = conn.execute(
            """SELECT wiki_beliefs.statement, wiki_beliefs.topic, wiki_beliefs.wiki_document_path
            FROM wiki_beliefs_fts
            JOIN wiki_beliefs ON wiki_beliefs.rowid = wiki_beliefs_fts.rowid
            WHERE wiki_beliefs_fts MATCH ? AND wiki_beliefs.workspace = ?
            AND wiki_beliefs.superseded_at IS NULL
            ORDER BY rank LIMIT ?""",
            (keyword, workspace, limit),
        ).fetchall()
        return [{"statement": r["statement"], "topic": r["topic"], "page": r["wiki_document_path"]} for r in rows]
    except Exception:
        return []
