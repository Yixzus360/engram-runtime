from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.adapters.run_longmemeval_v2_matrix import (
    MatrixRun,
    build_command,
    run_is_complete,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_ROOT = PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2"
DEFAULT_DATA_ROOT = OFFICIAL_ROOT / "data" / "longmemeval-v2"
DEFAULT_OUTPUT_ROOT = OFFICIAL_ROOT / "budget-curve-astra-study"
DEFAULT_STATE_PATH = OFFICIAL_ROOT / "budget-curve-state.json"
DEFAULT_PLAN_PATH = (
    PROJECT_ROOT / "benchmarks" / "scientific" / "longmemeval-v2-budget-curve-plan.json"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(state_path: Path, **updates: Any) -> None:
    state = read_json(state_path) if state_path.exists() else {}
    state.update(updates)
    state["updated_at_utc"] = datetime.now(UTC).isoformat()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_path)


def run_label(budget: int, method: str, domain: str) -> str:
    condition = "engram_on" if method == "engram_runtime" else "conventional_rag"
    return f"budget_{budget:05d}_{condition}_{domain}"


def validate_selection(plan: dict[str, Any], data_root: Path) -> None:
    selected = {
        question_id for ids in plan["selection"]["question_ids"].values() for question_id in ids
    }
    questions_path = data_root / "questions.jsonl"
    rows = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    found = {str(row["id"]): row for row in rows if str(row["id"]) in selected}
    if set(found) != selected:
        raise ValueError("The frozen budget-curve question set is incomplete in the dataset")
    for domain, question_ids in plan["selection"]["question_ids"].items():
        if len(question_ids) != plan["selection"]["questions_per_domain"]:
            raise ValueError(f"Unexpected frozen question count for {domain}")
        for question_id in question_ids:
            row = found[question_id]
            if row["domain"] != domain:
                raise ValueError(f"Question {question_id} has the wrong domain")
            if str(row["eval_function"]).startswith("llm_"):
                raise ValueError(f"Question {question_id} requires an LLM judge")


def build_budget_command(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    output_dir: Path,
    data_root: Path,
) -> list[str]:
    domain = str(entry["domain"])
    method = str(entry["method"])
    budget = int(entry["budget_tokens"])
    spec = MatrixRun(run_label(budget, method, domain), method, domain, 15)
    command = build_command(spec, output_dir, data_root=data_root)
    budget_index = command.index("--memory-context-max-tokens") + 1
    command[budget_index] = str(budget)
    command.extend(["--question-ids", *plan["selection"]["question_ids"][domain]])
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("ENGRAM_LONGMEMEVAL_DATA_ROOT", DEFAULT_DATA_ROOT)),
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    data_root = args.data_root.resolve()
    output_root = args.output_root.resolve()
    state_path = args.state_path.resolve()
    plan = read_json(plan_path)
    validate_selection(plan, data_root)
    output_root.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment.update(
        {
            "LONGMEMEVAL_V2_ROOT": str(OFFICIAL_ROOT),
            "PYTHONPATH": str(PROJECT_ROOT),
            "ENGRAM_LME_READER_TRANSPORT": "opencode",
            "ENGRAM_LME_EVALUATOR_TRANSPORT": "opencode",
            "LME_LOCAL_API_KEY": "local-opencode-transport",
            "LME_OAUTH_EVALUATOR_KEY": "unused-objective-subset",
            "ENGRAM_LME_EVALUATOR_USAGE_LOG": str(output_root / "evaluator-usage.jsonl"),
        }
    )
    completed: list[str] = []
    write_state(
        state_path,
        phase="running",
        pid=os.getpid(),
        plan=str(plan_path),
        output_root=str(output_root),
        expected_runs=plan["expected"]["runs"],
        expected_responses=plan["expected"]["responses"],
        completed_runs=completed,
        current_run=None,
        started_at_utc=datetime.now(UTC).isoformat(),
    )
    try:
        for entry in plan["execution_order"]:
            budget = int(entry["budget_tokens"])
            method = str(entry["method"])
            domain = str(entry["domain"])
            label = run_label(budget, method, domain)
            spec = MatrixRun(label, method, domain, 15)
            output_dir = output_root / label
            if run_is_complete(spec, output_dir):
                completed.append(label)
                write_state(state_path, completed_runs=completed)
                continue
            if output_dir.exists() and any(output_dir.iterdir()):
                raise RuntimeError(
                    f"Incomplete output exists for {label}: {output_dir}. "
                    "Archive it before rerunning the condition."
                )
            output_dir.mkdir(parents=True, exist_ok=True)
            write_state(state_path, current_run=label, completed_runs=completed)
            with (
                (output_dir / "runner.stdout.log").open("w", encoding="utf-8") as stdout,
                (output_dir / "runner.stderr.log").open("w", encoding="utf-8") as stderr,
            ):
                result = subprocess.run(
                    build_budget_command(
                        plan=plan,
                        entry=entry,
                        output_dir=output_dir,
                        data_root=data_root,
                    ),
                    cwd=PROJECT_ROOT,
                    env=environment,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                )
            if result.returncode != 0 or not run_is_complete(spec, output_dir):
                raise RuntimeError(f"Budget-curve run {label} failed with code {result.returncode}")
            completed.append(label)
            write_state(state_path, completed_runs=completed)
    except BaseException as exc:
        write_state(
            state_path,
            phase="failed",
            current_run=None,
            completed_runs=completed,
            failure_type=type(exc).__name__,
            failure=str(exc),
            pid=None,
        )
        raise

    write_state(
        state_path,
        phase="completed_pending_analysis",
        current_run=None,
        completed_runs=completed,
        finished_at_utc=datetime.now(UTC).isoformat(),
        pid=None,
    )


if __name__ == "__main__":
    main()
