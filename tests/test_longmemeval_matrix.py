from pathlib import Path

from benchmarks.adapters.run_longmemeval_v2_matrix import MatrixRun, build_command


def test_rag_matrix_command_keeps_frontier_reader_and_local_embeddings() -> None:
    data_root = Path("dataset")
    command = build_command(
        MatrixRun("rag", "rag_query_to_slice", "web", 240),
        Path("output"),
        data_root=data_root,
    )

    assert command[command.index("--data-root") + 1] == str(data_root)
    assert command[command.index("--reader-model") + 1] == "gpt-6-astra"
    assert command[command.index("--reader-max-concurrent-requests") + 1] == "2"
    assert command[command.index("--embedding-model") + 1] == "Qwen/Qwen3-Embedding-8B"
    assert command[command.index("--evaluator-model") + 1] == "gpt-5.5"
    assert "--no-reader-enable-thinking" in command
