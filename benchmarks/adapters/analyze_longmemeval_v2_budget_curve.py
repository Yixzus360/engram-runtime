from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.adapters.analyze_longmemeval_v2 import paired_comparison
from benchmarks.adapters.run_longmemeval_v2_budget_curve import run_label

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = PROJECT_ROOT / "benchmarks" / "scientific" / "longmemeval-v2-budget-curve-plan.json"
DEFAULT_ARTIFACT_ROOT = (
    PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2" / "budget-curve-astra-study"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "benchmarks" / "scientific" / "longmemeval-v2-budget-curve-results.json"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def summarize(rows: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    correct = sum(bool(row["score_bool"]) for row in rows)
    prompt_tokens = sum(int((row.get("usage") or {}).get("prompt_tokens", 0)) for row in rows)
    completion_tokens = sum(
        int((row.get("usage") or {}).get("completion_tokens", 0)) for row in rows
    )
    memory_tokens = sum(int(row.get("memory_context_token_count", 0)) for row in rows)
    return {
        "questions": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows),
        "unknown": sum(bool(row.get("is_unknown")) for row in rows),
        "reader_prompt_tokens": prompt_tokens,
        "reader_completion_tokens": completion_tokens,
        "memory_context_tokens": memory_tokens,
        "wall_seconds": wall_seconds,
        "correct_per_million_reader_prompt_tokens": (
            correct * 1_000_000 / prompt_tokens if prompt_tokens else None
        ),
    }


def analyze(plan_path: Path, artifact_root: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    runs: dict[str, Any] = {}
    rows_by_key: dict[tuple[int, str], list[dict[str, Any]]] = {}
    total_rows = 0
    for entry in plan["execution_order"]:
        budget = int(entry["budget_tokens"])
        method = str(entry["method"])
        domain = str(entry["domain"])
        label = run_label(budget, method, domain)
        run_dir = artifact_root / label
        rows_path = run_dir / "per_question.jsonl"
        rows = read_jsonl(rows_path)
        if len(rows) != plan["expected"]["responses_per_run"]:
            raise ValueError(f"{label}: unexpected response count")
        expected_ids = set(plan["selection"]["question_ids"][domain])
        if {str(row["question_id"]) for row in rows} != expected_ids:
            raise ValueError(f"{label}: question ids differ from the frozen plan")
        if any(str(row["eval_function"]).startswith("llm_") for row in rows):
            raise ValueError(f"{label}: LLM-judged row found in objective study")
        for row in rows:
            usage = row.get("usage") or {}
            if usage.get("requested_model") != "gpt-6-astra":
                raise ValueError(f"{label}: unexpected reader model")
            if usage.get("requested_variant") != "low":
                raise ValueError(f"{label}: unexpected reader variant")
            if usage.get("transport") != "opencode_cli_chatgpt_oauth":
                raise ValueError(f"{label}: unexpected reader transport")
            if int(row["memory_context_token_count"]) > budget:
                raise ValueError(f"{label}: memory context exceeded its budget")
        telemetry = json.loads((run_dir / "engram_run_telemetry.json").read_text(encoding="utf-8"))
        if telemetry.get("status") != "completed":
            raise ValueError(f"{label}: run telemetry is incomplete")
        runs[label] = {
            **summarize(rows, float(telemetry["wall_seconds"])),
            "budget_tokens": budget,
            "method": method,
            "domain": domain,
            "per_question_sha256": file_sha256(rows_path),
        }
        rows_by_key.setdefault((budget, method), []).extend(rows)
        total_rows += len(rows)

    if total_rows != plan["expected"]["responses"]:
        raise ValueError("The study does not contain the expected 240 responses")
    ledger_path = artifact_root / "evaluator-usage.jsonl"
    if ledger_path.exists() and ledger_path.read_text(encoding="utf-8").strip():
        raise ValueError("Objective budget curve unexpectedly called an LLM judge")

    curve: dict[str, Any] = {}
    for budget in plan["memory_context_budgets_tokens"]:
        engram_rows = rows_by_key[(budget, "engram_runtime")]
        rag_rows = rows_by_key[(budget, "rag_query_to_slice")]
        engram_wall = sum(
            run["wall_seconds"]
            for run in runs.values()
            if run["budget_tokens"] == budget and run["method"] == "engram_runtime"
        )
        rag_wall = sum(
            run["wall_seconds"]
            for run in runs.values()
            if run["budget_tokens"] == budget and run["method"] == "rag_query_to_slice"
        )
        engram = summarize(engram_rows, engram_wall)
        rag = summarize(rag_rows, rag_wall)
        comparison = paired_comparison(rag_rows, engram_rows, subset="deterministic")
        curve[str(budget)] = {
            "engram_runtime": engram,
            "rag_query_to_slice": rag,
            "engram_minus_rag": comparison,
            "engram_meets_token_quality_rule": (
                engram["accuracy"] >= rag["accuracy"]
                and engram["reader_prompt_tokens"] <= rag["reader_prompt_tokens"]
            ),
        }

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "benchmark": plan["benchmark"],
        "classification": plan["classification"],
        "plan_sha256": file_sha256(plan_path),
        "validation": {
            "complete_runs": len(runs),
            "responses": total_rows,
            "objective_scores": total_rows,
            "llm_judge_calls": 0,
            "reported_api_cost_usd": 0.0,
        },
        "runs": runs,
        "curve": curve,
        "claim_boundary": plan["claim_boundary"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = analyze(args.plan.resolve(), args.artifact_root.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["validation"], indent=2))


if __name__ == "__main__":
    main()
