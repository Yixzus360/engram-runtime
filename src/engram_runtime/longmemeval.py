from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

LONGMEMEVAL_DATASET_ID = "xiaowu0162/longmemeval-v2"
LONGMEMEVAL_DATASET_REVISION = "f152293e235517d504809563c833d7190b8c713b"


def text_dataset_allow_patterns(include_medium: bool) -> list[str]:
    patterns = [
        "questions.jsonl",
        "trajectories.jsonl",
        "haystacks/lme_v2_small.json",
        "question_screenshots/*",
    ]
    if include_medium:
        patterns.append("haystacks/lme_v2_medium.json")
    return patterns


def _text(value: Any, maximum: int = 1_200) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= maximum else normalized[: maximum - 1] + "…"


def trajectory_lines(trajectory: dict[str, object]) -> list[str]:
    """Create deterministic, text-only evidence without benchmark-private metadata."""
    trajectory_id = _text(trajectory.get("id"), 240) or "unknown"
    lines = [f"Trajectory: {trajectory_id}"]
    for label, key in (("Goal", "goal"), ("Start URL", "start_url"), ("Outcome", "outcome")):
        value = _text(trajectory.get(key), 2_000)
        if value:
            lines.append(f"{label}: {value}")
    actions = trajectory.get("actions")
    if isinstance(actions, list):
        for index, action in enumerate(actions):
            value = _text(action, 1_200)
            if value:
                lines.append(f"Action {index}: {value}")
    states = trajectory.get("states")
    if isinstance(states, list):
        for index, state in enumerate(states):
            if not isinstance(state, dict):
                continue
            parts: list[str] = []
            for label, keys in (
                ("url", ("url",)),
                ("action", ("action",)),
                ("thought", ("thought", "thoughts")),
                ("screen", ("accessibility_tree", "text")),
            ):
                value = next((_text(state.get(key)) for key in keys if state.get(key)), "")
                if value:
                    parts.append(f"{label}={value}")
            if parts:
                lines.append(f"State {index}: " + " | ".join(parts))
    content = trajectory.get("content")
    if isinstance(content, list):
        for index, item in enumerate(content):
            value = _text(item)
            if value:
                lines.append(f"Content {index}: {value}")
    return lines


def chunk_lines(lines: Iterable[str], *, maximum_characters: int = 3_500) -> list[str]:
    if maximum_characters < 500:
        raise ValueError("maximum_characters must be at least 500")
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for raw_line in lines:
        line = raw_line[:maximum_characters]
        projected = current_size + len(line) + (1 if current else 0)
        if current and projected > maximum_characters:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        current.append(line)
        current_size += len(line) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


def trajectory_chunks(
    trajectory: dict[str, object], *, maximum_characters: int = 3_500
) -> list[str]:
    return chunk_lines(trajectory_lines(trajectory), maximum_characters=maximum_characters)
