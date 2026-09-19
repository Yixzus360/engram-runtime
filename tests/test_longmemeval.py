from __future__ import annotations

from engram_runtime.longmemeval import (
    text_dataset_allow_patterns,
    trajectory_chunks,
    trajectory_lines,
)


def sample_trajectory() -> dict[str, object]:
    return {
        "id": "trajectory-1",
        "goal": "Update an account",
        "start_url": "https://example.test",
        "outcome": "Account updated",
        "states": [
            {
                "url": "https://example.test/account",
                "action": "click Save",
                "thought": "The fields are ready",
                "accessibility_tree": "Name field; Save button",
            }
        ],
    }


def test_trajectory_serialization_is_deterministic_and_text_only() -> None:
    first = trajectory_lines(sample_trajectory())
    second = trajectory_lines(sample_trajectory())
    assert first == second
    assert first[0] == "Trajectory: trajectory-1"
    assert any("click Save" in line for line in first)
    assert all("answer_gold" not in line for line in first)


def test_trajectory_chunks_respect_character_budget() -> None:
    trajectory = sample_trajectory()
    trajectory["states"] = [
        {"url": "https://example.test", "accessibility_tree": "x" * 1_000}
        for _ in range(5)
    ]
    chunks = trajectory_chunks(trajectory, maximum_characters=700)
    assert len(chunks) > 1
    assert all(len(chunk) <= 700 for chunk in chunks)


def test_text_first_download_excludes_trajectory_screenshot_archives() -> None:
    patterns = text_dataset_allow_patterns(include_medium=False)
    assert "trajectories.jsonl" in patterns
    assert "haystacks/lme_v2_small.json" in patterns
    assert not any("trajectory_screenshots" in pattern for pattern in patterns)
