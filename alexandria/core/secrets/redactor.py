"""Log redaction for known secret patterns.

Per amendment B5: regex-based redaction applied to all log output before
writing to disk. Covers common token/key patterns.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Patterns that match common secret shapes. Each is a compiled regex.
DEFAULT_PATTERNS: list[re.Pattern[str]] = [
    # Bearer tokens
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    # Authorization: token <value>
    re.compile(r"(Authorization:\s*token\s+)\S+", re.IGNORECASE),
    # GitHub PATs (classic and fine-grained)
    re.compile(r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{20,}"),
    # Anthropic API keys
    re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
    # OpenAI API keys
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # Generic API key in URL params
    re.compile(r"([?&](?:api_key|apikey|access_token|token)=)[^&\s]+", re.IGNORECASE),
    # password= in various contexts
    re.compile(r"(password\s*[=:]\s*)[^\s,;\"']+", re.IGNORECASE),
    # client_secret in various contexts
    re.compile(r"(client_secret\s*[=:]\s*)[^\s,;\"']+", re.IGNORECASE),
    # JWT tokens (three base64url segments separated by dots)
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # AWS access key IDs
    re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"),
]


class Redactor:
    """Applies regex-based redaction to text."""

    def __init__(self, extra_patterns: list[re.Pattern[str]] | None = None) -> None:
        self._patterns = list(DEFAULT_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def redact(self, text: str) -> str:
        """Replace all matching secret patterns with [REDACTED]."""
        result = text
        for pattern in self._patterns:
            if pattern.groups:
                # Patterns with groups: preserve the prefix, redact the value
                result = pattern.sub(rf"\1{REDACTED}", result)
            else:
                result = pattern.sub(REDACTED, result)
        return result

    def add_pattern(self, pattern: re.Pattern[str]) -> None:
        self._patterns.append(pattern)
