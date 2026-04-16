"""Tests for the budget enforcement system."""

from __future__ import annotations

import pytest

from llmwiki.llm.base import Usage
from llmwiki.llm.budget import BudgetConfig, BudgetEnforcer, BudgetExhausted


def test_budget_allows_within_limits() -> None:
    config = BudgetConfig(max_output_tokens=1000, max_usd=1.0)
    enforcer = BudgetEnforcer(config)

    usage = Usage(input_tokens=100, output_tokens=50)
    enforcer.record_writer(usage)
    enforcer.check_writer()  # should not raise


def test_budget_rejects_exceeded_tokens() -> None:
    config = BudgetConfig(max_output_tokens=100, max_usd=10.0)
    enforcer = BudgetEnforcer(config)

    usage = Usage(input_tokens=1000, output_tokens=150)
    enforcer.record_writer(usage)

    with pytest.raises(BudgetExhausted, match="output token"):
        enforcer.check_writer()


def test_budget_rejects_exceeded_usd() -> None:
    config = BudgetConfig(max_output_tokens=100_000, max_usd=0.001)
    enforcer = BudgetEnforcer(config)

    # Large enough to exceed $0.001
    usage = Usage(input_tokens=10_000, output_tokens=10_000)
    enforcer.record_writer(usage)

    with pytest.raises(BudgetExhausted, match="USD"):
        enforcer.check_writer()


def test_verifier_budget_is_multiplied() -> None:
    config = BudgetConfig(
        max_output_tokens=1000,
        max_usd=2.0,
        verifier_budget_multiplier=0.5,
    )
    assert config.verifier_max_output == 500
    assert config.verifier_max_usd == 1.0
    assert config.total_max_usd == 3.0


def test_verifier_budget_enforced_separately() -> None:
    config = BudgetConfig(max_output_tokens=10_000, max_usd=10.0, verifier_budget_multiplier=0.1)
    enforcer = BudgetEnforcer(config)

    # Writer budget is fine
    enforcer.record_writer(Usage(input_tokens=100, output_tokens=100))
    enforcer.check_writer()  # OK

    # Verifier budget is tiny (0.1 × 10000 = 1000 tokens)
    enforcer.record_verifier(Usage(input_tokens=100, output_tokens=1500))

    with pytest.raises(BudgetExhausted, match="Verifier"):
        enforcer.check_verifier()


def test_total_budget_combines_writer_and_verifier() -> None:
    config = BudgetConfig(max_usd=0.001, verifier_budget_multiplier=0.5)
    enforcer = BudgetEnforcer(config)

    # Each call is small but they add up
    for _ in range(20):
        enforcer.record_writer(Usage(input_tokens=500, output_tokens=500))
        enforcer.record_verifier(Usage(input_tokens=200, output_tokens=200))

    with pytest.raises(BudgetExhausted, match="Total USD"):
        enforcer.check_total()


def test_pre_flight_estimate() -> None:
    config = BudgetConfig()
    enforcer = BudgetEnforcer(config)

    est = enforcer.pre_flight_estimate(
        estimated_writer_calls=5,
        avg_input_per_call=3000,
        avg_output_per_call=1000,
        include_verifier=True,
    )
    assert est > 0
    assert isinstance(est, float)

    est_no_verifier = enforcer.pre_flight_estimate(
        estimated_writer_calls=5,
        avg_input_per_call=3000,
        avg_output_per_call=1000,
        include_verifier=False,
    )
    assert est_no_verifier < est


def test_usage_estimate_usd() -> None:
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    usd = usage.estimate_usd(
        input_price_per_mtok=5.0,
        output_price_per_mtok=25.0,
    )
    assert usd == pytest.approx(30.0, rel=0.01)


def test_usage_cache_discount() -> None:
    usage_no_cache = Usage(input_tokens=10_000, output_tokens=1_000)
    usage_with_cache = Usage(
        input_tokens=0,
        output_tokens=1_000,
        cache_read_tokens=10_000,
    )
    assert usage_with_cache.estimate_usd() < usage_no_cache.estimate_usd()
