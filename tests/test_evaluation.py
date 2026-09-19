from __future__ import annotations

import json
from pathlib import Path

from engram_runtime.evaluation import (
    BenchmarkTask,
    build_codex_command,
    parse_codex_jsonl,
)


def sample_task() -> BenchmarkTask:
    return BenchmarkTask(
        id="sample",
        question="Where is experience stored?",
        expected_terms=["engram_experience", "vector"],
        memory="Experience is stored in engram_experience with a vector index.",
    )


def test_jsonl_parser_extracts_usage_answer_tools_and_score() -> None:
    events = [
        {
            "type": "item.completed",
            "item": {"id": "tool-1", "type": "mcp_tool_call", "name": "recall_signals"},
        },
        {
            "type": "item.completed",
            "item": {
                "id": "answer-1",
                "type": "agent_message",
                "text": "engram_experience uses a vector index.",
            },
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 20,
                "reasoning_output_tokens": 5,
            },
        },
    ]
    result = parse_codex_jsonl(
        "\n".join(json.dumps(event) for event in events),
        task=sample_task(),
        mode="engram",
        model="test-model",
        reasoning_effort="low",
        elapsed_seconds=1.25,
        exit_code=0,
    )

    assert result.input_tokens == 100
    assert result.cached_input_tokens == 40
    assert result.tool_calls == 1
    assert result.score == 1.0


def test_commands_hold_model_effort_and_sandbox_constant() -> None:
    root = Path("C:/repo")
    baseline, _ = build_codex_command(
        workspace=root,
        server_root=root,
        task=sample_task(),
        mode="baseline",
        model="gpt-test",
        reasoning_effort="low",
        workspace_slug="test-workspace",
    )
    engram, _ = build_codex_command(
        workspace=root,
        server_root=root,
        task=sample_task(),
        mode="engram",
        model="gpt-test",
        reasoning_effort="low",
        workspace_slug="test-workspace",
    )

    for command in (baseline, engram):
        assert "--approve-for-me" in command
        assert command[command.index("--model") + 1] == "gpt-test"
        assert 'model_reasoning_effort="low"' in command
    assert not any("mcp_servers.engram" in item for item in baseline)
    assert any("mcp_servers.engram" in item for item in engram)
    assert any("ENGRAM_WORKSPACE_SLUG" in item for item in engram)
