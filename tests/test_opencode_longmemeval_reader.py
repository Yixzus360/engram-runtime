from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from benchmarks.adapters.opencode_longmemeval_reader import (
    _parse_json_events,
    materialize_message_parts,
)


def test_materialize_message_parts_preserves_text_image_order(tmp_path: Path) -> None:
    image = base64.b64encode(b"png-bytes").decode("ascii")
    messages = [
        {"role": "system", "content": "system rules"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "before"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image}"},
                },
                {"type": "text", "text": "after"},
            ],
        },
    ]

    paths = materialize_message_parts(messages, tmp_path)

    assert [path.suffix for path in paths] == [".txt", ".png"]
    prompt = paths[0].read_text(encoding="utf-8")
    assert prompt.index("system rules") < prompt.index("before")
    assert prompt.index("before") < prompt.index("ATTACHED IMAGE 1")
    assert prompt.index("ATTACHED IMAGE 1") < prompt.index("after")
    assert paths[1].read_bytes() == b"png-bytes"


def test_parse_json_events_extracts_text_usage_and_session() -> None:
    events = [
        {
            "type": "text",
            "sessionID": "ses_test",
            "part": {"text": "\\boxed{OK}"},
        },
        {
            "type": "step_finish",
            "sessionID": "ses_test",
            "part": {
                "reason": "stop",
                "cost": 0,
                "tokens": {
                    "total": 110,
                    "input": 100,
                    "output": 7,
                    "reasoning": 3,
                    "cache": {"read": 40, "write": 0},
                },
            },
        },
    ]

    text, usage = _parse_json_events("\n".join(json.dumps(item) for item in events))

    assert text == "\\boxed{OK}"
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 7
    assert usage["reasoning_tokens"] == 3
    assert usage["cached_input_tokens"] == 40
    assert usage["opencode_session_id"] == "ses_test"


def test_parse_json_events_rejects_error_event() -> None:
    with pytest.raises(RuntimeError, match="OpenCode reader error"):
        _parse_json_events(json.dumps({"type": "error", "error": {"name": "Failure"}}))
