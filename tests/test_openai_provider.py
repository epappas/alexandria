"""Tests for OpenAI provider."""

import json
from unittest.mock import patch, MagicMock

import pytest

from llmwiki.llm.base import CompletionRequest, Message
from llmwiki.llm.openai_provider import OpenAIProvider, OpenAICompatProvider


class TestOpenAIProvider:
    def test_build_payload(self) -> None:
        provider = OpenAIProvider(api_key="test-key")
        request = CompletionRequest(
            model="gpt-4o",
            system=[{"text": "You are helpful."}],
            tools=[],
            messages=[
                Message(role="user", content=[{"type": "text", "text": "Hello"}]),
            ],
        )
        payload = provider._build_payload(request, "gpt-4o")
        assert payload["model"] == "gpt-4o"
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"

    def test_parse_response(self) -> None:
        provider = OpenAIProvider()
        data = {
            "choices": [{
                "message": {"content": "Hello back!", "tool_calls": None},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = provider._parse_response(data, "gpt-4o")
        assert result.text == "Hello back!"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5
        assert result.stop_reason == "end_turn"

    def test_parse_tool_calls(self) -> None:
        provider = OpenAIProvider()
        data = {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "function": {"name": "search", "arguments": '{"q": "test"}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
        result = provider._parse_response(data, "gpt-4o")
        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "search"

    def test_estimate_cost(self) -> None:
        provider = OpenAIProvider()
        request = CompletionRequest(
            model="gpt-4o",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[{"type": "text", "text": "Hi"}])],
            max_output_tokens=100,
        )
        cost = provider.estimate_cost(request)
        assert cost > 0


class TestOpenAICompatProvider:
    def test_defaults(self) -> None:
        provider = OpenAICompatProvider()
        assert provider._base_url == "http://localhost:11434/v1"
        assert provider._default_model == "llama3"
        assert provider.name == "openai-compat"

    def test_custom_endpoint(self) -> None:
        provider = OpenAICompatProvider(
            base_url="http://my-vllm:8000/v1",
            default_model="mistral-7b",
        )
        assert provider._base_url == "http://my-vllm:8000/v1"
