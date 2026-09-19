from __future__ import annotations

import pytest

from engram_runtime.evaluation import BenchmarkTask, RunResult
from engram_runtime.scientific_evaluation import (
    ModelPrice,
    analyze_rows,
    api_equivalent_cost,
    build_plan,
    create_plan,
    ensure_study_lock,
    select_complete_pairs,
)


def task() -> BenchmarkTask:
    return BenchmarkTask("task-a", "Question?", ["answer"], "Memory")


def test_plan_is_reproducible_randomized_and_pair_complete() -> None:
    first = build_plan(
        tasks=[task()],
        models=["model-a", "model-b"],
        reasoning_effort="high",
        repetitions=3,
        seed=42,
    )
    second = build_plan(
        tasks=[task()],
        models=["model-a", "model-b"],
        reasoning_effort="high",
        repetitions=3,
        seed=42,
    )
    assert first == second
    assert len(first) == 12
    for pair_id in {item.pair_id for item in first}:
        pair = [item for item in first if item.pair_id == pair_id]
        assert {item.condition for item in pair} == {"baseline", "engram"}
        assert {item.pair_order for item in pair} == {1, 2}


def test_pair_limit_never_splits_a_pair() -> None:
    plan = build_plan(
        tasks=[task()],
        models=["model-a", "model-b"],
        reasoning_effort="high",
        repetitions=2,
        seed=4,
    )
    selected = select_complete_pairs(plan, 3)
    assert len(selected) == 6
    assert len({item.pair_id for item in selected}) == 3


def test_api_equivalent_uses_uncached_cached_and_output_rates() -> None:
    result = RunResult(
        task_id="task-a",
        mode="engram",
        model="model-a",
        reasoning_effort="high",
        elapsed_seconds=1.0,
        exit_code=0,
        input_tokens=100,
        cached_input_tokens=40,
        output_tokens=20,
        reasoning_output_tokens=0,
        tool_calls=1,
        expected_terms_found=1,
        expected_terms_total=1,
        answer="answer",
    )
    price = ModelPrice(10.0, 1.0, 50.0)
    assert api_equivalent_cost(result, price) == (60 * 10 + 40 + 20 * 50) / 1_000_000


def test_analysis_uses_only_complete_pairs() -> None:
    rows = [
        {
            "pair_id": "p1",
            "condition": "baseline",
            "completed": False,
            "score": 0.0,
            "uncached_input_tokens": 100,
            "api_equivalent_usd": 1.0,
            "run": {"elapsed_seconds": 5.0},
        },
        {
            "pair_id": "p1",
            "condition": "engram",
            "completed": True,
            "score": 1.0,
            "uncached_input_tokens": 80,
            "api_equivalent_usd": 0.8,
            "run": {"elapsed_seconds": 4.0},
        },
        {
            "pair_id": "incomplete",
            "condition": "baseline",
            "completed": True,
            "score": 1.0,
            "uncached_input_tokens": 50,
            "api_equivalent_usd": 0.5,
            "run": {"elapsed_seconds": 2.0},
        },
    ]
    analysis = analyze_rows(rows, seed=1)
    assert analysis["complete_pairs"] == 1
    assert analysis["primary_endpoint"]["engram_only_success"] == 1
    assert analysis["primary_endpoint"]["engram_minus_baseline"]["estimate"] == 1.0


def test_create_plan_can_select_a_diagnostic_subset(tmp_path) -> None:
    benchmark_dir = tmp_path / "benchmarks" / "codex"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "tasks.json").write_text(
        '[{"id":"task-a","question":"Q","expected_terms":[],"memory":"M"}]',
        encoding="utf-8",
    )
    protocol = {
        "models": ["model-a", "model-b"],
        "design": {"reasoning_effort": "high", "random_seed": 1},
        "task_source": {
            "path": "benchmarks/codex/tasks.json",
            "family": "test",
        },
    }
    plan = create_plan(
        tmp_path,
        protocol,
        1,
        model_filters=["model-b"],
        task_filters=["task-a"],
    )
    assert len(plan) == 2
    assert {item.model for item in plan} == {"model-b"}


def test_study_lock_freezes_source_and_rejects_changed_inputs(tmp_path) -> None:
    for directory in ("src", "docs", "benchmarks/codex"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "src" / "runtime.py").write_text("VERSION = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "method.md").write_text("method\n", encoding="utf-8")
    for filename in ("README.md", "pyproject.toml", "LICENSE"):
        (tmp_path / filename).write_text(filename, encoding="utf-8")
    (tmp_path / "benchmarks" / "codex" / "tasks.json").write_text(
        "[]", encoding="utf-8"
    )
    protocol = {"task_source": {"path": "benchmarks/codex/tasks.json"}}
    output_dir = tmp_path / "output"
    snapshot = ensure_study_lock(root=tmp_path, protocol=protocol, output_dir=output_dir)
    assert (snapshot / "src" / "runtime.py").read_text(encoding="utf-8") == "VERSION = 1\n"

    (tmp_path / "src" / "runtime.py").write_text("VERSION = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Study inputs changed"):
        ensure_study_lock(root=tmp_path, protocol=protocol, output_dir=output_dir)
