"""Anthropic provider — the first-class LLM backend.

Per ``11_inference_endpoint.md`` and ``PLAN_AMENDMENTS.md`` B2:
- Tool use via native ``tools`` parameter.
- **Mandatory prompt caching from day one** — ``cache_control: ephemeral``
  on the last tool definition and the last stable system block.
- Streaming deferred to Phase 6 daemon; this phase uses synchronous calls.
- Error taxonomy: rate limit (429/529), auth (401), content policy (400),
  transport (5xx), with exponential backoff + jitter on retryable errors.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

from alexandria.llm.base import (
    CompletionRequest,
    CompletionResult,
    Usage,
)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 30.0


class AnthropicProviderError(Exception):
    """Raised on non-retryable Anthropic API errors."""


class AnthropicProvider:
    """Synchronous Anthropic Messages API provider with prompt caching.

    Requires ``ANTHROPIC_API_KEY`` in the environment or passed explicitly.
    """

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_MODEL,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._default_model = default_model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init the Anthropic client."""
        if self._client is None:
            if not self._api_key:
                raise AnthropicProviderError(
                    "ANTHROPIC_API_KEY not set. Run: alexandria secrets set anthropic_key"
                )
            try:
                import anthropic
            except ImportError as exc:
                raise AnthropicProviderError(
                    "anthropic package not installed. Run: pip install anthropic"
                ) from exc
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Call the Anthropic Messages API with prompt caching and retries."""
        client = self._get_client()
        model = request.model or self._default_model

        # Build tools with cache_control on the last one
        tools = _build_tools(request.tools)

        # Build system blocks with cache_control on the last stable one
        system = _build_system(request.system)

        # Build messages
        messages = _build_messages(request.messages)

        # Retry loop with exponential backoff
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=request.max_output_tokens,
                    system=system,
                    tools=tools if tools else [],  # type: ignore
                    messages=messages,
                    **({"temperature": request.temperature} if request.temperature is not None else {}),
                )
                return _parse_response(response)
            except Exception as exc:
                last_error = exc
                if _is_retryable(exc) and attempt < MAX_RETRIES:
                    delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                    time.sleep(delay)
                    continue
                if _is_auth_error(exc):
                    raise AnthropicProviderError(
                        f"Authentication failed: {exc}. Check your ANTHROPIC_API_KEY."
                    ) from exc
                raise AnthropicProviderError(f"Anthropic API error: {exc}") from exc

        raise AnthropicProviderError(f"All {MAX_RETRIES} retries failed: {last_error}")

    def estimate_cost(self, request: CompletionRequest) -> float:
        """Rough pre-flight USD estimate without making a call."""
        # Estimate input tokens from system + messages length
        system_chars = sum(len(str(b)) for b in request.system)
        messages_chars = sum(
            sum(len(str(b)) for b in m.content) for m in request.messages
        )
        est_input = (system_chars + messages_chars) // 4
        est_output = request.max_output_tokens // 2  # assume ~50% of max
        usage = Usage(input_tokens=est_input, output_tokens=est_output)
        return usage.estimate_usd()


def _build_tools(tools: list[Any]) -> list[dict[str, Any]]:
    """Convert ToolDefinitions to Anthropic API format with cache hints."""
    if not tools:
        return []
    result: list[dict[str, Any]] = []
    for i, tool in enumerate(tools):
        entry: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        # Per B2: cache_control on the LAST tool → caches the entire tools array
        if i == len(tools) - 1:
            entry["cache_control"] = {"type": "ephemeral"}
        result.append(entry)
    return result


def _build_system(system_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add cache_control to the last stable system block."""
    if not system_blocks:
        return []
    result = list(system_blocks)
    # Cache the last system block (the stable orientation content)
    if result:
        last = dict(result[-1])
        last["cache_control"] = {"type": "ephemeral"}
        result[-1] = last
    return result


def _build_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert Messages to Anthropic API format."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": msg.role,
            "content": msg.content,
        }
        result.append(entry)
    return result


def _parse_response(response: Any) -> CompletionResult:
    """Parse the Anthropic API response into our CompletionResult."""
    content: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })

    usage = Usage(
        input_tokens=getattr(response.usage, "input_tokens", 0),
        output_tokens=getattr(response.usage, "output_tokens", 0),
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
        cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0),
    )

    return CompletionResult(
        content=content,
        stop_reason=response.stop_reason or "end_turn",
        usage=usage,
        model=response.model,
    )


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is retryable (rate limit, overloaded, transport)."""
    exc_str = str(type(exc).__name__).lower()
    msg = str(exc).lower()
    return any(kw in exc_str or kw in msg for kw in [
        "ratelimit", "rate_limit", "429", "529", "overloaded",
        "timeout", "connection", "502", "503", "504",
    ])


def _is_auth_error(exc: Exception) -> bool:
    """Check if an exception is an authentication error."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ["401", "authentication", "invalid.*key", "unauthorized"])
