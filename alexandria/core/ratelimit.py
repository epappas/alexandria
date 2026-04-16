"""Token-bucket rate limiter.

Per ``16_operations_and_reliability.md``: shared rate limiter across all
source adapters. Each adapter declares its limits; the rate limiter tracks
remaining capacity and blocks when the budget is exhausted.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Configuration for a token bucket."""

    max_tokens: float
    refill_rate: float  # tokens per second
    name: str = ""


class TokenBucket:
    """Thread-safe token-bucket rate limiter.

    Tokens refill at ``refill_rate`` per second up to ``max_tokens``.
    ``acquire()`` blocks until a token is available (with timeout) or
    returns False if the wait would exceed the deadline.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._max = config.max_tokens
        self._rate = config.refill_rate
        self._name = config.name
        self._tokens = config.max_tokens
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    def acquire(self, count: float = 1.0, timeout: float = 30.0) -> bool:
        """Acquire ``count`` tokens, blocking up to ``timeout`` seconds.

        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= count:
                    self._tokens -= count
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            wait = min(count / max(self._rate, 0.001), remaining)
            time.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._max, self._tokens + elapsed * self._rate)
        self._last_refill = now


class RateLimiter:
    """Registry of named token buckets.

    Usage:
        limiter = RateLimiter()
        limiter.register("github", RateLimitConfig(max_tokens=5000, refill_rate=5000/3600))
        if limiter.acquire("github"):
            do_github_call()
    """

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def register(self, name: str, config: RateLimitConfig) -> None:
        config.name = name
        with self._lock:
            self._buckets[name] = TokenBucket(config)

    def acquire(self, name: str, count: float = 1.0, timeout: float = 30.0) -> bool:
        with self._lock:
            bucket = self._buckets.get(name)
        if bucket is None:
            raise KeyError(f"no rate limiter registered for {name!r}")
        return bucket.acquire(count, timeout)

    def available(self, name: str) -> float:
        with self._lock:
            bucket = self._buckets.get(name)
        if bucket is None:
            raise KeyError(f"no rate limiter registered for {name!r}")
        return bucket.available

    def registered(self) -> list[str]:
        with self._lock:
            return list(self._buckets.keys())
