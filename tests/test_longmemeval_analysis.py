import pytest

from benchmarks.adapters.analyze_longmemeval_v2 import (
    exact_mcnemar_p,
    paired_comparison,
    relative_reduction,
)


def _row(question_id: str, score: bool) -> dict[str, object]:
    return {
        "question_id": question_id,
        "score_bool": score,
        "eval_function": "exact_match",
    }


def test_paired_comparison_counts_gains_and_losses() -> None:
    baseline = [_row("a", False), _row("b", True), _row("c", False)]
    treatment = [_row("a", True), _row("b", False), _row("c", True)]

    result = paired_comparison(baseline, treatment, subset="deterministic")

    assert result["pairs"] == 3
    assert result["gains"] == 2
    assert result["losses"] == 1
    assert result["delta_accuracy"] == 1 / 3


def test_exact_mcnemar_handles_no_discordance() -> None:
    assert exact_mcnemar_p(0, 0) == 1.0


def test_relative_reduction_uses_baseline_as_denominator() -> None:
    assert relative_reduction(25, 100) == 0.75
    with pytest.raises(ValueError, match="zero baseline"):
        relative_reduction(0, 0)
