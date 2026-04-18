"""LLM-powered content processing for the ingest pipeline.

Calls the configured LLM to:
1. Summarize source content into a wiki page
2. Extract structured beliefs (claims with citations)
3. Generate footnote citations linking claims to source quotes
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from typing import Any, Coroutine, TypeVar

from alexandria.llm.base import CompletionRequest, CompletionResult, Message

T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine, handling both sync and async caller contexts.

    Uses asyncio.run() normally. When called from inside an existing event
    loop (e.g. MCP server), offloads to a thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop — run in a separate thread
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


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

    try:
        result = provider.complete(request)
    except RuntimeError:
        return None
    return _parse_llm_response(result, raw_path)


def _get_provider() -> Any | None:
    """Get the configured LLM provider, or None if not configured.

    Detection order:
    1. [llm] section in config.toml (most explicit)
    2. Claude Code SDK (uses Max/Pro subscription, no API key needed)
    3. ANTHROPIC_API_KEY env var -> Anthropic
    4. OPENAI_API_KEY env var -> OpenAI
    5. OPENROUTER_API_KEY env var -> OpenRouter (OpenAI-compat)
    6. GOOGLE_API_KEY env var -> Google/Gemini (OpenAI-compat)
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

    # 2. Claude Code SDK — uses Max/Pro subscription directly, no API key
    if _has_claude_code_sdk():
        return _ClaudeCodeSDKProvider()

    # 3. Environment variable auto-detection
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


def _has_claude_code_sdk() -> bool:
    """Check if the claude CLI is available for subprocess calls.

    Returns False if we're inside an active Claude Code session (CLAUDECODE=1)
    to avoid nested rate-limit conflicts.
    """
    if os.environ.get("CLAUDECODE") == "1":
        return False
    import shutil
    from pathlib import Path
    if not shutil.which("claude"):
        return False
    creds = Path.home() / ".claude" / ".credentials.json"
    return creds.exists()


class _ClaudeCodeSDKProvider:
    """LLM provider using the Claude Code SDK with Max/Pro subscription.

    Uses your Claude subscription directly — no API key needed.
    Calls the Claude Code binary under the hood via the SDK.
    """

    name = "claude-code-sdk"

    def complete(self, request: CompletionRequest) -> CompletionResult:
        import shutil
        import subprocess

        # Build the prompt from the request
        system_text = "\n".join(
            b.get("text", "") for b in request.system
        ) if request.system else ""

        user_text = ""
        for msg in request.messages:
            if msg.role == "user":
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        user_text += block.get("text", "")

        full_prompt = f"{system_text}\n\n{user_text}" if system_text else user_text

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("claude CLI not found in PATH")

        result = subprocess.run(
            [claude_bin, "-p", "--output-format", "text", full_prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "rate" in stderr.lower() or "limit" in stderr.lower():
                raise RuntimeError(
                    "Rate limited by Claude Max subscription. "
                    "Close any other Claude Code sessions and retry, "
                    "or set ANTHROPIC_API_KEY for independent API access."
                )
            raise RuntimeError(f"claude -p failed: {stderr[:200]}")

        text = result.stdout.strip()

        from alexandria.llm.base import Usage
        return CompletionResult(
            content=[{"type": "text", "text": text}],
            stop_reason="end_turn",
            usage=Usage(),
            model="claude-code-sdk",
        )

    def estimate_cost(self, request: CompletionRequest) -> float:
        return 0.0  # subscription — no per-call cost


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
