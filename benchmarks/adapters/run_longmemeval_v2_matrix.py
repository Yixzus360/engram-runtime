from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_ROOT = PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2"
DEFAULT_DATA_ROOT = OFFICIAL_ROOT / "data" / "longmemeval-v2"
DEFAULT_OUTPUT_ROOT = OFFICIAL_ROOT / "opencode-astra-study"
DEFAULT_STATE_PATH = OFFICIAL_ROOT / "longmemeval-state.json"
WRAPPER = PROJECT_ROOT / "benchmarks" / "adapters" / "run_longmemeval_v2.py"


@dataclass(frozen=True)
class MatrixRun:
    label: str
    method: str
    domain: str
    expected_questions: int


RUNS = (
    MatrixRun("engram_off_web", "no_retrieval", "web", 240),
    MatrixRun("conventional_rag_web", "rag_query_to_slice", "web", 240),
    MatrixRun("engram_on_web", "engram_runtime", "web", 240),
    MatrixRun("engram_on_enterprise", "engram_runtime", "enterprise", 211),
    MatrixRun("conventional_rag_enterprise", "rag_query_to_slice", "enterprise", 211),
    MatrixRun("engram_off_enterprise", "no_retrieval", "enterprise", 211),
)


def _read_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _write_state(state_path: Path, **updates: Any) -> None:
    state = _read_state(state_path)
    state.update(updates)
    state["phase_updated_at"] = datetime.now(UTC).isoformat()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_path)


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def run_is_complete(spec: MatrixRun, output_dir: Path) -> bool:
    telemetry_path = output_dir / "engram_run_telemetry.json"
    if not telemetry_path.exists():
        return False
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    return (
        telemetry.get("status") == "completed"
        and _jsonl_count(output_dir / "per_question.jsonl") == spec.expected_questions
    )


def build_command(
    spec: MatrixRun, output_dir: Path, *, data_root: Path = DEFAULT_DATA_ROOT
) -> list[str]:
    command = [
        sys.executable,
        str(WRAPPER),
        "--data-root",
        str(data_root),
        "--domain",
        spec.domain,
        "--tier",
        "small",
        "--method",
        spec.method,
        "--output-dir",
        str(output_dir),
        "--reader-model",
        "gpt-6-astra",
        "--reader-base-url",
        "http://127.0.0.1:1/v1",
        "--reader-api-key-env",
        "LME_LOCAL_API_KEY",
        "--reader-max-concurrent-requests",
        "2",
        "--max-completion-tokens",
        "20000",
        "--memory-context-max-tokens",
        "200000",
        "--no-reader-enable-thinking",
        "--evaluator-model",
        "gpt-5.5",
        "--evaluator-api-key-env",
        "LME_OAUTH_EVALUATOR_KEY",
        "--evaluator-reasoning-effort",
        "medium",
        "--evaluator-max-completion-tokens",
        "4096",
        "--prompt-build-max-workers",
        "2",
    ]
    if spec.method == "rag_query_to_slice":
        command.extend(
            [
                "--controller-model",
                "qwen3.5-9b",
                "--controller-base-url",
                "http://localhost:11434/v1",
                "--controller-api-key-env",
                "LME_LOCAL_API_KEY",
                "--controller-disable-thinking",
                "--embedding-model",
                "Qwen/Qwen3-Embedding-8B",
                "--embedding-base-url",
                "http://localhost:11434/v1",
                "--embedding-api-key-env",
                "LME_LOCAL_API_KEY",
            ]
        )
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("ENGRAM_LONGMEMEVAL_DATA_ROOT", DEFAULT_DATA_ROOT)),
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    output_root = args.output_root.resolve()
    state_path = args.state_path.resolve()
    if not data_root.exists():
        raise FileNotFoundError(
            f"LongMemEval-V2 data root not found: {data_root}. Pass --data-root or set "
            "ENGRAM_LONGMEMEVAL_DATA_ROOT."
        )
    output_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "LONGMEMEVAL_V2_ROOT": str(OFFICIAL_ROOT),
            "PYTHONPATH": str(PROJECT_ROOT),
            "ENGRAM_LME_READER_TRANSPORT": "opencode",
            "ENGRAM_LME_EVALUATOR_TRANSPORT": "opencode",
            "LME_LOCAL_API_KEY": "local-opencode-transport",
            "LME_OAUTH_EVALUATOR_KEY": "local-opencode-oauth-transport",
            "ENGRAM_LME_EVALUATOR_USAGE_LOG": str(output_root / "evaluator-usage.jsonl"),
        }
    )
    completed: list[str] = []
    _write_state(
        state_path,
        phase="running_opencode_astra_frontier_matrix",
        matrix_pid=os.getpid(),
        matrix_output_root=str(output_root),
        matrix_completed_runs=completed,
        matrix_total_runs=len(RUNS),
        matrix_expected_reader_calls=1353,
        matrix_expected_llm_grades=468,
        matrix_expected_deterministic_grades=885,
        matrix_evaluator_model="gpt-5.5",
        matrix_evaluator_transport="opencode_cli_chatgpt_oauth",
        matrix_evaluator_direct_api_budget_usd=0,
    )
    try:
        for spec in RUNS:
            output_dir = output_root / spec.label
            if run_is_complete(spec, output_dir):
                completed.append(spec.label)
                _write_state(state_path, matrix_completed_runs=completed)
                continue
            if output_dir.exists() and any(output_dir.iterdir()):
                raise RuntimeError(
                    f"Incomplete output exists for {spec.label}: {output_dir}. "
                    "Archive it before rerunning the condition."
                )
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_state(
                state_path,
                matrix_current_run=spec.label,
                matrix_completed_runs=completed,
            )
            with (
                (output_dir / "runner.stdout.log").open("w", encoding="utf-8") as stdout,
                (output_dir / "runner.stderr.log").open("w", encoding="utf-8") as stderr,
            ):
                result = subprocess.run(
                    build_command(spec, output_dir, data_root=data_root),
                    cwd=PROJECT_ROOT,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
            if result.returncode != 0 or not run_is_complete(spec, output_dir):
                raise RuntimeError(f"Matrix run {spec.label} failed with code {result.returncode}")
            completed.append(spec.label)
            _write_state(state_path, matrix_completed_runs=completed)
    except BaseException as exc:
        _write_state(
            state_path,
            phase="opencode_astra_frontier_matrix_failed",
            matrix_failure_type=type(exc).__name__,
            matrix_failure=str(exc),
            matrix_completed_runs=completed,
        )
        raise
    _write_state(
        state_path,
        phase="opencode_astra_matrix_completed_pending_analysis",
        matrix_current_run=None,
        matrix_completed_runs=completed,
        matrix_finished_at=datetime.now(UTC).isoformat(),
    )


if __name__ == "__main__":
    main()
