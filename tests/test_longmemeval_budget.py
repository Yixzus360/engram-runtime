import json

import pytest

from benchmarks.adapters.longmemeval_budget import EvaluatorBudget, EvaluatorPricing


def test_budget_accounts_for_cached_and_output_tokens(tmp_path):
    budget = EvaluatorBudget(
        tmp_path / "usage.jsonl",
        maximum_usd=1,
        pricing=EvaluatorPricing(2.0, 0.5, 10.0),
    )
    call_id, reserved = budget.reserve(
        model="judge",
        messages=[{"role": "user", "content": "hello"}],
        max_completion_tokens=100,
    )
    actual = budget.settle(
        call_id,
        model="judge",
        input_tokens=1_000,
        cached_input_tokens=400,
        output_tokens=100,
        reserved_usd=reserved,
    )

    assert actual == pytest.approx(0.0024)
    assert budget.spent_or_reserved_usd() == pytest.approx(actual)


def test_budget_refuses_a_call_before_crossing_cap(tmp_path):
    log = tmp_path / "usage.jsonl"
    log.write_text(
        json.dumps(
            {
                "call_id": "previous",
                "status": "settled",
                "actual_usd": 0.99,
                "reserved_usd": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    budget = EvaluatorBudget(
        log,
        maximum_usd=1,
        pricing=EvaluatorPricing(2.0, 0.5, 10.0),
    )

    with pytest.raises(RuntimeError, match="budget would be exceeded"):
        budget.reserve(
            model="judge",
            messages=[{"role": "user", "content": "hello"}],
            max_completion_tokens=2_000,
        )
