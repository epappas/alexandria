"""LLM-powered query — the LLM drives everything.

1. LLM extracts structured search terms from the question
2. Searches across all knowledge sources using those terms
3. LLM reads the retrieved context + original question
4. LLM produces a grounded answer with citations

No regex, no stop words, no keyword hacks. The LLM understands the question.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from alexandria.db.connection import sanitize_fts_query
from alexandria.llm.base import CompletionRequest, Message

KEYWORD_PROMPT = """You are a search query planner for a knowledge base. Given a user question, extract the key search terms that would find relevant documents.

Rules:
- Return 3-6 search terms as a JSON array of strings
- Fix obvious typos (e.g., "forr" -> "for")
- Use the root/canonical form of words (e.g., "memories" -> "memory")
- Include both specific terms and broader related terms
- Do NOT include stop words or filler words

Example:
Question: "what do we know forr agentic memory?"
Output: ["agentic", "memory", "episodic", "context", "LLM"]

Question: "{question}"
Output:"""

ANSWER_PROMPT = """You are a knowledge assistant. Answer the user's question using ONLY the provided context from the knowledge base.

Rules:
- Be concise and factual
- Cite sources using [Source: title] format
- If the context doesn't contain enough information, say what you found and what's missing
- Do not make up information beyond what's in the context

Context:
{context}

Question: {question}

Answer:"""


def llm_query(
    conn: sqlite3.Connection,
    workspace: str,
    question: str,
    limit: int = 10,
) -> dict[str, Any] | None:
    """Answer a question using LLM-powered retrieval and synthesis.

    Returns None if no LLM is available — the caller should tell the user
    to configure a provider.
    """
    from alexandria.core.llm_ingest import _get_provider
    provider = _get_provider()
    if provider is None:
        return None

    # Step 1: LLM extracts search terms
    keywords = _extract_keywords(provider, question)

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
        return {
            "answer": "No relevant information found in the knowledge base for this question.",
            "sources": [],
            "beliefs": [],
            "keywords": keywords,
        }

    # Step 4: LLM synthesizes answer from context
    answer = _generate_answer(provider, question, context)

    return {
        "answer": answer,
        "sources": [{"title": d["title"], "path": d["path"]} for d in all_docs[:limit]],
        "beliefs": [{"statement": b["statement"], "topic": b["topic"]} for b in all_beliefs[:limit]],
        "keywords": keywords,
    }


def _extract_keywords(provider: Any, question: str) -> list[str]:
    """LLM extracts search terms from the question."""
    request = CompletionRequest(
        model="",
        system=[],
        tools=[],
        messages=[
            Message(role="user", content=[{
                "type": "text",
                "text": KEYWORD_PROMPT.format(question=question),
            }]),
        ],
        max_output_tokens=100,
        temperature=0.0,
    )
    result = provider.complete(request)
    text = result.text.strip()

    # Parse JSON array from response
    if text.startswith("```"):
        text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("```"))
    try:
        keywords = json.loads(text)
        if isinstance(keywords, list):
            return [str(k).strip() for k in keywords if str(k).strip()][:6]
    except json.JSONDecodeError:
        pass

    # If JSON parsing fails, the LLM returned plain text — split it
    return [w.strip().strip('"[],') for w in text.split() if len(w.strip('"[],')) > 2][:6]


def _generate_answer(provider: Any, question: str, context: str) -> str:
    """LLM synthesizes an answer from retrieved context."""
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
    result = provider.complete(request)
    return result.text.strip()


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
    try:
        rows = conn.execute(
            """SELECT documents.title, documents.path, documents.content
            FROM documents_fts
            JOIN documents ON documents.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ? AND documents.workspace = ?
            ORDER BY rank LIMIT ?""",
            (sanitize_fts_query(keyword), workspace, limit),
        ).fetchall()
        return [{"title": r["title"], "path": r["path"], "content": r["content"] or ""} for r in rows]
    except Exception:
        return []


def _fts_search_beliefs(conn: sqlite3.Connection, workspace: str, keyword: str, limit: int) -> list[dict]:
    try:
        rows = conn.execute(
            """SELECT wiki_beliefs.statement, wiki_beliefs.topic, wiki_beliefs.wiki_document_path
            FROM wiki_beliefs_fts
            JOIN wiki_beliefs ON wiki_beliefs.rowid = wiki_beliefs_fts.rowid
            WHERE wiki_beliefs_fts MATCH ? AND wiki_beliefs.workspace = ?
            AND wiki_beliefs.superseded_at IS NULL
            ORDER BY rank LIMIT ?""",
            (sanitize_fts_query(keyword), workspace, limit),
        ).fetchall()
        return [{"statement": r["statement"], "topic": r["topic"], "page": r["wiki_document_path"]} for r in rows]
    except Exception:
        return []
