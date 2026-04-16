"""OpenAI LLM provider.

Implements the LLMProvider protocol for OpenAI API and compatible endpoints
(Ollama, vLLM, SGLang, LM Studio via OpenAI-compatible API).
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from llmwiki.llm.base import (
    CompletionRequest,
    CompletionResult,
    Message,
    Usage,
)


class OpenAIProvider:
    """OpenAI and OpenAI-compatible LLM provider."""

    name = "openai"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o",
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout

    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Run a single completion against the OpenAI API."""
        model = request.model or self._default_model
        payload = self._build_payload(request, model)

        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(
                f"OpenAI API error {exc.code}: {exc.read().decode()}"
            ) from exc

        return self._parse_response(data, model)

    def estimate_cost(self, request: CompletionRequest) -> float:
        """Rough cost estimate based on token counts."""
        # Approximate: 1 token ~= 4 chars
        total_chars = sum(
            len(json.dumps(m.content)) for m in request.messages
        )
        est_input = total_chars // 4
        est_output = request.max_output_tokens
        # GPT-4o pricing: $2.50/M input, $10/M output
        return (est_input / 1_000_000) * 2.5 + (est_output / 1_000_000) * 10.0

    def _build_payload(self, request: CompletionRequest, model: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []

        # System messages
        if request.system:
            for sys_block in request.system:
                messages.append({"role": "system", "content": sys_block.get("text", "")})

        # Conversation messages
        for msg in request.messages:
            role = msg.role
            if role == "tool_result":
                role = "tool"
            content = msg.content
            if isinstance(content, list):
                # Flatten content blocks to text
                text_parts = [
                    b.get("text", "") for b in content if b.get("type") == "text"
                ]
                content = "\n".join(text_parts) if text_parts else json.dumps(content)
            messages.append({"role": role, "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        return payload

    def _parse_response(self, data: dict[str, Any], model: str) -> CompletionResult:
        choice = data["choices"][0]
        message = choice["message"]

        content_blocks = [{"type": "text", "text": message.get("content", "")}]
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "input": json.loads(tc["function"].get("arguments", "{}")),
                })

        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        stop_reason = "end_turn"
        if choice.get("finish_reason") == "tool_calls":
            stop_reason = "tool_use"
        elif choice.get("finish_reason") == "length":
            stop_reason = "max_tokens"

        return CompletionResult(
            content=content_blocks,
            stop_reason=stop_reason,
            usage=usage,
            model=model,
        )


class OpenAICompatProvider(OpenAIProvider):
    """OpenAI-compatible provider for Ollama, vLLM, SGLang, LM Studio."""

    name = "openai-compat"

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        default_model: str = "llama3",
        api_key: str = "",
        timeout: int = 120,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            timeout=timeout,
        )
