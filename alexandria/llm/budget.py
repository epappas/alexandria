"""Budget enforcement for LLM calls.

Per ``PLAN_AMENDMENTS.md`` B3: ships in Phase 2b with three hard mechanisms:
1. Verifier multiplier as a config value.
2. Per-run hard ceiling that aborts before the N+1th call.
3. Pre-flight cost estimator for dry-run previews.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alexandria.llm.base import Usage


class BudgetExhausted(Exception):
    """Raised when a run exceeds its configured budget."""

    def __init__(self, message: str, usage: "RunUsage") -> None:
        super().__init__(message)
        self.usage = usage


@dataclass
class BudgetConfig:
    """Budget limits for a single operation type."""

    max_input_tokens: int = 200_000
    max_output_tokens: int = 50_000
    max_usd: float = 2.00
    verifier_budget_multiplier: float = 0.5

    @property
    def verifier_max_input(self) -> int:
        return int(self.max_input_tokens * self.verifier_budget_multiplier)

    @property
    def verifier_max_output(self) -> int:
        return int(self.max_output_tokens * self.verifier_budget_multiplier)

    @property
    def verifier_max_usd(self) -> float:
        return self.max_usd * self.verifier_budget_multiplier

    @property
    def total_max_usd(self) -> float:
        return self.max_usd + self.verifier_max_usd


@dataclass
class RunUsage:
    """Cumulative usage tracking for an entire run (writer + verifier)."""

    writer_input_tokens: int = 0
    writer_output_tokens: int = 0
    writer_cache_read_tokens: int = 0
    writer_cache_write_tokens: int = 0
    writer_usd: float = 0.0
    writer_calls: int = 0

    verifier_input_tokens: int = 0
    verifier_output_tokens: int = 0
    verifier_cache_read_tokens: int = 0
    verifier_cache_write_tokens: int = 0
    verifier_usd: float = 0.0
    verifier_calls: int = 0

    @property
    def total_usd(self) -> float:
        return self.writer_usd + self.verifier_usd

    @property
    def total_input_tokens(self) -> int:
        return self.writer_input_tokens + self.verifier_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self.writer_output_tokens + self.verifier_output_tokens

    def add_writer_usage(self, usage: Usage) -> None:
        self.writer_input_tokens += usage.input_tokens
        self.writer_output_tokens += usage.output_tokens
        self.writer_cache_read_tokens += usage.cache_read_tokens
        self.writer_cache_write_tokens += usage.cache_write_tokens
        self.writer_usd += usage.estimate_usd()
        self.writer_calls += 1

    def add_verifier_usage(self, usage: Usage) -> None:
        self.verifier_input_tokens += usage.input_tokens
        self.verifier_output_tokens += usage.output_tokens
        self.verifier_cache_read_tokens += usage.cache_read_tokens
        self.verifier_cache_write_tokens += usage.cache_write_tokens
        self.verifier_usd += usage.estimate_usd()
        self.verifier_calls += 1


class BudgetEnforcer:
    """Checks cumulative run usage against configured budget limits.

    Call ``check_writer()`` before every writer LLM call and
    ``check_verifier()`` before every verifier LLM call. Raises
    ``BudgetExhausted`` if the next call would exceed the limit.
    """

    def __init__(self, config: BudgetConfig) -> None:
        self.config = config
        self.usage = RunUsage()

    def check_writer(self) -> None:
        """Raise if the writer budget is exhausted."""
        if self.usage.writer_output_tokens >= self.config.max_output_tokens:
            raise BudgetExhausted(
                f"Writer output token budget exhausted: "
                f"{self.usage.writer_output_tokens} >= {self.config.max_output_tokens}",
                self.usage,
            )
        if self.usage.writer_usd >= self.config.max_usd:
            raise BudgetExhausted(
                f"Writer USD budget exhausted: "
                f"${self.usage.writer_usd:.4f} >= ${self.config.max_usd:.2f}",
                self.usage,
            )

    def check_verifier(self) -> None:
        """Raise if the verifier budget is exhausted."""
        if self.usage.verifier_output_tokens >= self.config.verifier_max_output:
            raise BudgetExhausted(
                f"Verifier output token budget exhausted: "
                f"{self.usage.verifier_output_tokens} >= {self.config.verifier_max_output}",
                self.usage,
            )
        if self.usage.verifier_usd >= self.config.verifier_max_usd:
            raise BudgetExhausted(
                f"Verifier USD budget exhausted: "
                f"${self.usage.verifier_usd:.4f} >= ${self.config.verifier_max_usd:.2f}",
                self.usage,
            )

    def check_total(self) -> None:
        """Raise if the combined writer + verifier budget is exhausted."""
        if self.usage.total_usd >= self.config.total_max_usd:
            raise BudgetExhausted(
                f"Total USD budget exhausted: "
                f"${self.usage.total_usd:.4f} >= ${self.config.total_max_usd:.2f}",
                self.usage,
            )

    def record_writer(self, usage: Usage) -> None:
        """Record a writer LLM call's usage."""
        self.usage.add_writer_usage(usage)

    def record_verifier(self, usage: Usage) -> None:
        """Record a verifier LLM call's usage."""
        self.usage.add_verifier_usage(usage)

    def pre_flight_estimate(
        self,
        estimated_writer_calls: int,
        avg_input_per_call: int,
        avg_output_per_call: int,
        include_verifier: bool = True,
    ) -> float:
        """Estimate total USD before running. For --dry-run previews."""
        writer_input = estimated_writer_calls * avg_input_per_call
        writer_output = estimated_writer_calls * avg_output_per_call
        writer_usage = Usage(input_tokens=writer_input, output_tokens=writer_output)
        total = writer_usage.estimate_usd()

        if include_verifier:
            verifier_calls = max(1, estimated_writer_calls // 2)
            v_input = verifier_calls * avg_input_per_call
            v_output = verifier_calls * (avg_output_per_call // 2)
            v_usage = Usage(input_tokens=v_input, output_tokens=v_output)
            total += v_usage.estimate_usd()

        return total
