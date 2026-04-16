"""LLM provider abstraction.

Per ``11_inference_endpoint.md``: one abstract contract, multiple
implementations. Typed, sync (async deferred to Phase 6+ daemon),
tool-use-aware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolDefinition:
    """A tool the LLM can call."""

    name: str
    description: str
    input_schema: dict[str, Any]
    cache_hint: bool = False


@dataclass(frozen=True)
class Message:
    """A conversation message."""

    role: str  # "user" | "assistant" | "tool_result"
    content: list[dict[str, Any]]
    cache_hint: bool = False


@dataclass(frozen=True)
class CompletionRequest:
    """A request to the LLM provider."""

    model: str
    system: list[dict[str, Any]]
    tools: list[ToolDefinition]
    messages: list[Message]
    max_output_tokens: int = 4096
    temperature: float | None = None


@dataclass
class Usage:
    """Token usage from a single completion call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def estimate_usd(
        self,
        input_price_per_mtok: float = 5.0,
        output_price_per_mtok: float = 25.0,
        cache_read_multiplier: float = 0.1,
        cache_write_multiplier: float = 1.25,
    ) -> float:
        """Estimate USD cost from token counts and Anthropic-style pricing."""
        base_input_cost = (self.input_tokens / 1_000_000) * input_price_per_mtok
        cache_read_cost = (self.cache_read_tokens / 1_000_000) * input_price_per_mtok * cache_read_multiplier
        cache_write_cost = (self.cache_write_tokens / 1_000_000) * input_price_per_mtok * cache_write_multiplier
        output_cost = (self.output_tokens / 1_000_000) * output_price_per_mtok
        return base_input_cost + cache_read_cost + cache_write_cost + output_cost


@dataclass
class CompletionResult:
    """Result from a single LLM completion."""

    content: list[dict[str, Any]]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: Usage
    model: str = ""

    @property
    def text(self) -> str:
        """Extract plain text from the response content blocks."""
        parts: list[str] = []
        for block in self.content:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """Extract tool_use blocks from the response."""
        return [b for b in self.content if b.get("type") == "tool_use"]


class LLMProvider(Protocol):
    """Abstract interface for LLM providers.

    Implementations:
    - ``AnthropicProvider`` (Phase 2b) — real Anthropic API with prompt caching.
    - ``OpenAIProvider`` (Phase 8) — OpenAI / GPT models.
    - ``OpenAICompatProvider`` (Phase 8) — Ollama, vLLM, SGLang, LM Studio.
    """

    name: str

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Run a single completion. Blocks until the response is ready."""
        ...

    def estimate_cost(self, request: CompletionRequest) -> float:
        """Pre-flight USD estimate without making a call."""
        ...
