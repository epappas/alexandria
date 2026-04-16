"""Tests for circuit breaker state transitions."""

import time

from alexandria.core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_check_raises_when_open(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        try:
            cb.check()
            assert False, "expected CircuitOpenError"
        except CircuitOpenError as exc:
            assert exc.name == "test"
            assert exc.retry_after >= 0

    def test_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(
            "test", CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.05)
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker(
            "test", CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.01)
        )
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker(
            "test", CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.01)
        )
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # resets count
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # still below threshold

    def test_manual_reset(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    def test_auto_creates(self) -> None:
        reg = CircuitBreakerRegistry()
        cb = reg.get("new_source")
        assert cb.state == CircuitState.CLOSED

    def test_returns_same_instance(self) -> None:
        reg = CircuitBreakerRegistry()
        cb1 = reg.get("src")
        cb2 = reg.get("src")
        assert cb1 is cb2

    def test_states(self) -> None:
        reg = CircuitBreakerRegistry()
        reg.get("a")
        reg.get("b").record_failure()
        states = reg.states()
        assert states["a"] == CircuitState.CLOSED
