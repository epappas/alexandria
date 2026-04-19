"""Circuit breaker for source adapters.

Per ``16_operations_and_reliability.md``: three-state breaker per adapter.
Prevents hammering a failing source and allows automatic recovery.

States:
  CLOSED  -> normal operation, failures counted
  OPEN    -> requests immediately rejected, cool-down timer running
  HALF_OPEN -> one probe request allowed; success resets, failure re-opens
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Tuning knobs for a circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds before OPEN -> HALF_OPEN
    success_threshold: int = 1       # successes in HALF_OPEN before closing


class CircuitOpenError(Exception):
    """Raised when the circuit is open and rejecting calls."""

    def __init__(self, name: str, retry_after: float) -> None:
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"circuit breaker '{name}' is open; retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """Per-adapter circuit breaker with three states."""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def check(self) -> None:
        """Raise ``CircuitOpenError`` if the circuit is open."""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.OPEN:
                retry_after = (
                    self._last_failure_time
                    + self._config.recovery_timeout
                    - time.monotonic()
                )
                raise CircuitOpenError(self._name, max(0.0, retry_after))

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._success_count = 0
            elif self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the breaker to closed."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0

    def _maybe_transition_to_half_open(self) -> None:
        """Check if enough time has passed to probe. Must hold _lock."""
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self._config.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0


class CircuitBreakerRegistry:
    """Manages circuit breakers for all source adapters."""

    def __init__(self, default_config: CircuitBreakerConfig | None = None) -> None:
        self._default_config = default_config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> CircuitBreaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, self._default_config)
            return self._breakers[name]

    def states(self) -> dict[str, CircuitState]:
        with self._lock:
            return {name: cb.state for name, cb in self._breakers.items()}
