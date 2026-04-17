"""LLM-powered content processing for the ingest pipeline.

Calls the configured LLM to:
1. Summarize source content into a wiki page
2. Extract structured beliefs (claims with citations)
3. Generate footnote citations linking claims to source quotes
"""

from __future__ import annotations

import json
import os
from typing import Any

from alexandria.llm.base import CompletionRequest, CompletionResult, Message


SYSTEM_PROMPT = """You are a knowledge engineer for a personal wiki. Given a source document, produce a structured wiki page with:

1. A concise summary (3-5 paragraphs) of the key ideas
2. Structured beliefs — specific factual claims made in the source
3. Footnote citations linking each claim to a verbatim quote from the source

Output format (strict JSON):
{
  "title": "concise descriptive title",
  "summary": "markdown summary with inline [^N] footnote references on key claims",
  "beliefs": [
    {
      "statement": "specific factual claim",
      "topic": "category/subject area",
      "subject": "entity the claim is about",
      "predicate": "relationship verb",
      "object": "what is claimed about the subject",
      "quote": "exact verbatim quote from the source supporting this claim",
      "footnote_id": "1"
    }
  ]
}

Rules:
- Every belief MUST have a verbatim quote copied exactly from the source text
- The summary MUST reference beliefs via [^N] inline
- Keep the summary factual and grounded — no speculation
- Extract 3-10 beliefs depending on content density
- The title should be descriptive, not the URL or filename"""


def llm_process_content(
    source_content: str,
    source_name: str,
    raw_path: str,
) -> dict[str, Any] | None:
    """Call the LLM to process source content into a wiki page.

    Returns dict with: title, body (markdown with footnotes), beliefs list.
    Returns None if no LLM is configured.
    """
    provider = _get_provider()
    if provider is None:
        return None

    # Truncate very long content to fit context
    content = source_content[:50_000]

    request = CompletionRequest(
        model="",  # use provider default
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        tools=[],
        messages=[
            Message(
                role="user",
                content=[{
                    "type": "text",
                    "text": f"Source document: {source_name}\n\n---\n\n{content}",
                }],
            ),
        ],
        max_output_tokens=4096,
        temperature=0.2,
    )

    result = provider.complete(request)
    return _parse_llm_response(result, raw_path)


def _get_provider() -> Any | None:
    """Get the configured LLM provider, or None if not configured.

    Detection order:
    1. [llm] section in config.toml (most explicit)
    2. ANTHROPIC_API_KEY env var -> Anthropic
    3. OPENAI_API_KEY env var -> OpenAI
    4. OPENROUTER_API_KEY env var -> OpenRouter (OpenAI-compat)
    5. GOOGLE_API_KEY env var -> Google/Gemini (OpenAI-compat)
    """
    # 1. Config file takes priority — user explicitly configured it
    try:
        from alexandria.config import load_config, resolve_home
        config = load_config(resolve_home())
        llm_cfg = config.llm

        if llm_cfg.provider and llm_cfg.provider != "none":
            key = ""
            if llm_cfg.api_key_env:
                key = os.environ.get(llm_cfg.api_key_env, "")
            # Allow keyless for local providers (ollama, vllm)
            if key or llm_cfg.base_url:
                return _build_provider(llm_cfg.provider, key, llm_cfg.model, llm_cfg.base_url)
    except Exception:
        pass

    # 2. Environment variable auto-detection
    for env_var, provider_name, base_url, default_model in [
        ("ANTHROPIC_API_KEY", "anthropic", "", ""),
        ("OPENAI_API_KEY", "openai", "", "gpt-4o"),
        ("OPENROUTER_API_KEY", "openai-compat", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4"),
        ("GOOGLE_API_KEY", "openai-compat", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    ]:
        key = os.environ.get(env_var, "")
        if key:
            return _build_provider(provider_name, key, default_model, base_url)

    return None


def _build_provider(provider: str, api_key: str, model: str, base_url: str) -> Any:
    """Instantiate the right provider class."""
    if provider == "anthropic":
        from alexandria.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=api_key, default_model=model or "claude-sonnet-4-20250514")

    if provider == "openai":
        from alexandria.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=api_key, default_model=model or "gpt-4o",
                              base_url=base_url or "https://api.openai.com/v1")

    if provider == "openai-compat":
        from alexandria.llm.openai_provider import OpenAICompatProvider
        return OpenAICompatProvider(api_key=api_key, default_model=model or "llama3",
                                    base_url=base_url or "http://localhost:11434/v1")

    raise ValueError(f"unknown LLM provider: {provider}")


def _parse_llm_response(result: CompletionResult, raw_path: str) -> dict[str, Any] | None:
    """Parse the LLM JSON response into a structured wiki page."""
    text = result.text.strip()

    # Extract JSON from response (may be wrapped in markdown code block)
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(json_lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    title = data.get("title", "Untitled")
    summary = data.get("summary", "")
    beliefs_raw = data.get("beliefs", [])

    # Build footnote section
    footnotes: list[str] = []
    beliefs: list[dict[str, Any]] = []
    for b in beliefs_raw:
        fn_id = b.get("footnote_id", str(len(footnotes) + 1))
        quote = b.get("quote", "")
        if quote:
            footnotes.append(f'[^{fn_id}]: {raw_path} — "{quote}"')
        beliefs.append({
            "statement": b.get("statement", ""),
            "topic": b.get("topic", ""),
            "subject": b.get("subject"),
            "predicate": b.get("predicate"),
            "object": b.get("object"),
            "footnote_ids": [fn_id],
        })

    body = summary
    if footnotes:
        body += "\n\n" + "\n".join(footnotes)

    return {
        "title": title,
        "body": body,
        "beliefs": beliefs,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
    }
