from __future__ import annotations

import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    lower: float
    estimate: float
    upper: float


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("at least one value is required")
    return sum(values) / len(values)


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("at least one value is required")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def paired_bootstrap_interval(
    deltas: Sequence[float],
    *,
    confidence: float = 0.95,
    samples: int = 10_000,
    seed: int = 0,
) -> Interval:
    if not deltas:
        raise ValueError("at least one paired delta is required")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if samples < 1:
        raise ValueError("samples must be positive")
    generator = random.Random(seed)
    size = len(deltas)
    estimates = [
        mean([deltas[generator.randrange(size)] for _ in range(size)])
        for _ in range(samples)
    ]
    alpha = (1 - confidence) / 2
    return Interval(
        lower=percentile(estimates, alpha),
        estimate=mean(deltas),
        upper=percentile(estimates, 1 - alpha),
    )


def exact_mcnemar_p_value(baseline_only_success: int, engram_only_success: int) -> float:
    """Two-sided exact McNemar test over discordant paired binary outcomes."""
    if baseline_only_success < 0 or engram_only_success < 0:
        raise ValueError("discordant counts cannot be negative")
    discordant = baseline_only_success + engram_only_success
    if discordant == 0:
        return 1.0
    tail = min(baseline_only_success, engram_only_success)
    probability = sum(math.comb(discordant, index) for index in range(tail + 1))
    return min(1.0, 2 * probability / (2**discordant))


def paired_sign_flip_p_value(
    deltas: Sequence[float],
    *,
    samples: int = 100_000,
    seed: int = 0,
) -> float:
    """Two-sided paired randomization test for a zero mean effect."""
    nonzero = [float(value) for value in deltas if value != 0]
    if not nonzero:
        return 1.0
    observed = abs(mean(nonzero))
    count = len(nonzero)
    if count <= 20:
        outcomes = itertools.product((-1, 1), repeat=count)
        extreme = 0
        total = 0
        for signs in outcomes:
            estimate = abs(
                mean([value * sign for value, sign in zip(nonzero, signs, strict=True)])
            )
            extreme += estimate >= observed - 1e-12
            total += 1
        return extreme / total

    generator = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        estimate = abs(
            mean([value if generator.random() < 0.5 else -value for value in nonzero])
        )
        extreme += estimate >= observed - 1e-12
    return (extreme + 1) / (samples + 1)
