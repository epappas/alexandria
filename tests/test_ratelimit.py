"""Tests for rate limiter token bucket."""

import time

from llmwiki.core.ratelimit import RateLimitConfig, RateLimiter, TokenBucket


class TestTokenBucket:
    def test_initial_capacity(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=10, refill_rate=1.0))
        assert bucket.available == 10.0

    def test_acquire_decrements(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=10, refill_rate=1.0))
        assert bucket.acquire(3) is True
        assert bucket.available <= 7.1  # allow small refill

    def test_acquire_blocks_until_refill(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=1, refill_rate=100.0))
        assert bucket.acquire(1) is True
        # Should refill quickly at 100/s
        assert bucket.acquire(1, timeout=1.0) is True

    def test_acquire_timeout(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=1, refill_rate=0.001))
        bucket.acquire(1)
        # Very slow refill, should timeout
        assert bucket.acquire(1, timeout=0.01) is False

    def test_max_cap(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=5, refill_rate=1000.0))
        time.sleep(0.02)  # let it refill
        assert bucket.available <= 5.0

    def test_name(self) -> None:
        bucket = TokenBucket(RateLimitConfig(max_tokens=1, refill_rate=1, name="test"))
        assert bucket.name == "test"


class TestRateLimiter:
    def test_register_and_acquire(self) -> None:
        limiter = RateLimiter()
        limiter.register("github", RateLimitConfig(max_tokens=10, refill_rate=1.0))
        assert limiter.acquire("github")

    def test_unknown_raises(self) -> None:
        limiter = RateLimiter()
        try:
            limiter.acquire("unknown")
            assert False, "expected KeyError"
        except KeyError:
            pass

    def test_registered_names(self) -> None:
        limiter = RateLimiter()
        limiter.register("a", RateLimitConfig(max_tokens=1, refill_rate=1))
        limiter.register("b", RateLimitConfig(max_tokens=1, refill_rate=1))
        assert sorted(limiter.registered()) == ["a", "b"]

    def test_available(self) -> None:
        limiter = RateLimiter()
        limiter.register("x", RateLimitConfig(max_tokens=5, refill_rate=1))
        assert limiter.available("x") == 5.0
