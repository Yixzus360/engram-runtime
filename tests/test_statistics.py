from __future__ import annotations

import pytest

from engram_runtime.statistics import (
    exact_mcnemar_p_value,
    paired_bootstrap_interval,
    paired_sign_flip_p_value,
)


def test_exact_mcnemar_handles_balanced_and_one_sided_discordance() -> None:
    assert exact_mcnemar_p_value(0, 0) == 1.0
    assert exact_mcnemar_p_value(3, 3) == 1.0
    assert exact_mcnemar_p_value(0, 6) == pytest.approx(0.03125)


def test_bootstrap_is_reproducible_and_preserves_constant_effect() -> None:
    first = paired_bootstrap_interval([2.0, 2.0, 2.0], samples=100, seed=7)
    second = paired_bootstrap_interval([2.0, 2.0, 2.0], samples=100, seed=7)
    assert first == second
    assert (first.lower, first.estimate, first.upper) == (2.0, 2.0, 2.0)


def test_sign_flip_detects_consistent_direction() -> None:
    assert paired_sign_flip_p_value([1.0] * 6) == pytest.approx(0.03125)
