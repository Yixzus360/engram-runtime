from pathlib import Path

from benchmarks.adapters.analyze_longmemeval_v2_budget_curve import summarize
from benchmarks.adapters.run_longmemeval_v2_budget_curve import (
    build_budget_command,
    run_label,
)


def test_budget_command_fixes_context_cap_and_questions() -> None:
    plan = {"selection": {"question_ids": {"web": ["a", "b"]}}}
    command = build_budget_command(
        plan=plan,
        entry={
            "budget_tokens": 8192,
            "method": "engram_runtime",
            "domain": "web",
        },
        output_dir=Path("output"),
        data_root=Path("dataset"),
    )

    assert command[command.index("--memory-context-max-tokens") + 1] == "8192"
    assert command[command.index("--question-ids") + 1 :] == ["a", "b"]
    assert command[command.index("--reader-model") + 1] == "gpt-6-astra"
    assert "--no-reader-enable-thinking" in command


def test_budget_run_label_is_stable() -> None:
    assert (
        run_label(4096, "rag_query_to_slice", "enterprise")
        == "budget_04096_conventional_rag_enterprise"
    )


def test_budget_summary_reports_token_efficiency() -> None:
    result = summarize(
        [
            {
                "score_bool": True,
                "is_unknown": False,
                "memory_context_token_count": 100,
                "usage": {"prompt_tokens": 200, "completion_tokens": 5},
            },
            {
                "score_bool": False,
                "is_unknown": True,
                "memory_context_token_count": 120,
                "usage": {"prompt_tokens": 300, "completion_tokens": 7},
            },
        ],
        wall_seconds=4.0,
    )

    assert result["accuracy"] == 0.5
    assert result["reader_prompt_tokens"] == 500
    assert result["correct_per_million_reader_prompt_tokens"] == 2000
