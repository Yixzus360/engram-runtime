from __future__ import annotations

import pytest

from engram_runtime.blind_debate import (
    aggregate_debate,
    build_blind_labels,
    parse_json_answer,
    rotate_answers,
)


def rows() -> list[dict[str, object]]:
    return [{"model": model} for model in ("model-c", "model-a", "model-b")]


def test_blind_labels_are_reproducible_and_hide_model_names() -> None:
    first = build_blind_labels(rows(), seed=9)
    second = build_blind_labels(rows(), seed=9)
    assert first == second
    assert set(first.values()) == {"Response A", "Response B", "Response C"}
    assert all(model not in label for model, label in first.items())


def test_rotation_changes_position_without_changing_labels() -> None:
    answers = {"Response A": "a", "Response B": "b", "Response C": "c"}
    first = rotate_answers(answers, judge_index=0)
    second = rotate_answers(answers, judge_index=1)
    assert first != second
    assert set(first) == set(second)


def test_json_answer_accepts_fenced_json() -> None:
    payload = parse_json_answer('```json\n{"best_label":"Response A"}\n```')
    assert payload["best_label"] == "Response A"


def test_aggregate_records_jury_disagreement_and_objective_score() -> None:
    labels = {"model-a": "Response A", "model-b": "Response B"}
    jury = [
        {
            "judge_model": "judge-1",
            "verdict": {
                "ranking": [
                    {"label": "Response A", "score": 90, "critique": "good"},
                    {"label": "Response B", "score": 80, "critique": "ok"},
                ],
                "best_label": "Response A",
                "confidence": 0.8,
            },
        },
        {
            "judge_model": "judge-2",
            "verdict": {
                "ranking": [
                    {"label": "Response A", "score": 70, "critique": "ok"},
                    {"label": "Response B", "score": 95, "critique": "good"},
                ],
                "best_label": "Response B",
                "confidence": 0.7,
            },
        },
    ]
    result = aggregate_debate(
        jury_rows=jury,
        labels_by_model=labels,
        objective_scores={"Response A": 1.0, "Response B": 0.5},
    )
    assert result["valid_judges"] == 2
    assert result["jury_disagreement_rate"] == pytest.approx(0.5)
    assert {item["objective_score"] for item in result["ranking"]} == {1.0, 0.5}
