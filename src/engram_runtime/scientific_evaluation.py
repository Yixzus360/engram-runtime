from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .evaluation import (
    BenchmarkTask,
    RunResult,
    load_tasks,
    prepare_snapshot,
    run_codex,
    seed_memory,
)
from .statistics import (
    exact_mcnemar_p_value,
    paired_bootstrap_interval,
    paired_sign_flip_p_value,
)

Condition = Literal["baseline", "engram"]


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    pair_id: str
    task_id: str
    task_family: str
    model: str
    reasoning_effort: str
    repetition: int
    condition: Condition
    pair_order: int
    seed: int


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def load_prices(path: Path) -> dict[str, ModelPrice]:
    payload = load_json(path)
    return {
        model: ModelPrice(
            input_per_million=float(values["input_per_million"]),
            cached_input_per_million=float(values["cached_input_per_million"]),
            output_per_million=float(values["output_per_million"]),
        )
        for model, values in payload["models"].items()
    }


def api_equivalent_cost(result: RunResult, price: ModelPrice) -> float:
    return (
        result.uncached_input_tokens * price.input_per_million
        + result.cached_input_tokens * price.cached_input_per_million
        + result.output_tokens * price.output_per_million
    ) / 1_000_000


def build_plan(
    *,
    tasks: list[BenchmarkTask],
    models: list[str],
    reasoning_effort: str,
    repetitions: int,
    seed: int,
    task_family: str = "internal_repo_qa",
) -> list[PlannedRun]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    generator = random.Random(seed)
    pairs: list[tuple[str, BenchmarkTask, int]] = [
        (model, task, repetition)
        for model in models
        for task in tasks
        for repetition in range(1, repetitions + 1)
    ]
    generator.shuffle(pairs)
    plan: list[PlannedRun] = []
    for model, task, repetition in pairs:
        pair_id = f"{_slug(model)}__{task.id}__r{repetition:02d}"
        conditions: list[Condition] = ["baseline", "engram"]
        generator.shuffle(conditions)
        pair_seed = generator.randrange(0, 2**31)
        for order, condition in enumerate(conditions, start=1):
            plan.append(
                PlannedRun(
                    run_id=f"{pair_id}__{condition}",
                    pair_id=pair_id,
                    task_id=task.id,
                    task_family=task_family,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    repetition=repetition,
                    condition=condition,
                    pair_order=order,
                    seed=pair_seed,
                )
            )
    return plan


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def append_jsonl_batch(path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist a complete comparison pair in one flushed write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def study_digest(root: Path, protocol: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for directory in ("src", "docs"):
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    for filename in ("README.md", "pyproject.toml", "LICENSE"):
        path = root / filename
        digest.update(filename.encode("utf-8"))
        digest.update(path.read_bytes())
    task_path = root / protocol["task_source"]["path"]
    digest.update(task_path.relative_to(root).as_posix().encode("utf-8"))
    digest.update(task_path.read_bytes())
    digest.update(json.dumps(protocol, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def ensure_study_lock(
    *, root: Path, protocol: dict[str, Any], output_dir: Path
) -> Path:
    lock_path = output_dir / "study-lock.json"
    results_path = output_dir / "results.jsonl"
    current_digest = study_digest(root, protocol)
    if lock_path.exists():
        saved = load_json(lock_path)
        if saved.get("study_digest") != current_digest:
            raise RuntimeError(
                "Study inputs changed after the first run. Use a new output directory."
            )
    else:
        if results_path.exists():
            raise RuntimeError(
                "Existing results predate study locking. Use a new output directory."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(
                {
                    "locked_at": datetime.now(UTC).isoformat(),
                    "study_digest": current_digest,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    source_snapshot = output_dir / "source"
    completion_marker = source_snapshot / ".complete"
    if source_snapshot.exists() and not completion_marker.exists():
        resolved_source = source_snapshot.resolve()
        if output_dir.resolve() not in resolved_source.parents:
            raise RuntimeError(f"Refusing to reset snapshot outside {output_dir.resolve()}")
        shutil.rmtree(resolved_source)
    if not source_snapshot.exists():
        prepare_snapshot(root, source_snapshot)
        completion_marker.write_text(current_digest + "\n", encoding="utf-8")
    return source_snapshot


def select_complete_pairs(plan: list[PlannedRun], max_pairs: int | None) -> list[PlannedRun]:
    if max_pairs is None:
        return plan
    if max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    pair_ids: list[str] = []
    for item in plan:
        if item.pair_id not in pair_ids:
            pair_ids.append(item.pair_id)
        if len(pair_ids) == max_pairs:
            break
    selected = set(pair_ids)
    return [item for item in plan if item.pair_id in selected]


def ordered_plan_pairs(plan: list[PlannedRun]) -> list[list[PlannedRun]]:
    grouped: dict[str, list[PlannedRun]] = {}
    for item in plan:
        grouped.setdefault(item.pair_id, []).append(item)
    pairs = list(grouped.values())
    for pair in pairs:
        if len(pair) != 2 or {item.condition for item in pair} != {"baseline", "engram"}:
            raise RuntimeError(f"Invalid comparison pair in plan: {pair[0].pair_id}")
        if {item.pair_order for item in pair} != {1, 2}:
            raise RuntimeError(f"Invalid pair order in plan: {pair[0].pair_id}")
        pair.sort(key=lambda item: item.pair_order)
    return pairs


def completed_pair_ids(rows: list[dict[str, Any]]) -> set[str]:
    """Accept resumable results only when every persisted pair is complete and runnable."""
    seen_run_ids: set[str] = set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        run_id = str(row["run_id"])
        if run_id in seen_run_ids:
            raise RuntimeError(f"Duplicate run in existing results: {run_id}")
        seen_run_ids.add(run_id)
        if int(row.get("run", {}).get("exit_code", 0)) != 0:
            raise RuntimeError(
                "Existing results contain an infrastructure failure. "
                "Start a clean output directory."
            )
        grouped[str(row["pair_id"])].append(row)
    completed: set[str] = set()
    for pair_id, pair_rows in grouped.items():
        if len(pair_rows) != 2 or {row["condition"] for row in pair_rows} != {
            "baseline",
            "engram",
        }:
            raise RuntimeError(
                f"Existing results contain an incomplete comparison pair: {pair_id}"
            )
        completed.add(pair_id)
    return completed


def result_record(item: PlannedRun, result: RunResult, price: ModelPrice) -> dict[str, Any]:
    raw = asdict(result)
    return {
        **asdict(item),
        "capture_key": hashlib.sha256(item.run_id.encode("utf-8")).hexdigest()[:12],
        "recorded_at": datetime.now(UTC).isoformat(),
        "completed": result.exit_code == 0 and result.score == 1.0,
        "score": result.score,
        "uncached_input_tokens": result.uncached_input_tokens,
        "error_count": 1 if result.error else 0,
        "retry_count": None,
        "model_invocation_proxy": 1,
        "context_consumption_metric": "codex_reported_cumulative_input_tokens",
        "actual_billed_usd": None,
        "api_equivalent_usd": api_equivalent_cost(result, price),
        "run": raw,
    }


def paired_records(rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[row["pair_id"]][row["condition"]] = row
    return [
        (conditions["baseline"], conditions["engram"])
        for conditions in grouped.values()
        if {"baseline", "engram"} <= conditions.keys()
    ]


def _value(row: dict[str, Any], metric: str) -> float:
    if metric in row:
        return float(row[metric])
    return float(row["run"][metric])


def _has_metric(row: dict[str, Any], metric: str) -> bool:
    return metric in row or metric in row.get("run", {})


def _metric_deltas(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]], metric: str
) -> list[float]:
    return [_value(engram, metric) - _value(baseline, metric) for baseline, engram in pairs]


def analyze_rows(rows: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    pairs = paired_records(rows)
    if not pairs:
        raise ValueError("No complete baseline/Engram pairs are available")
    baseline_only = sum(
        bool(baseline["completed"]) and not bool(engram["completed"])
        for baseline, engram in pairs
    )
    engram_only = sum(
        bool(engram["completed"]) and not bool(baseline["completed"])
        for baseline, engram in pairs
    )
    candidate_metrics = (
        "score",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "api_equivalent_usd",
        "elapsed_seconds",
        "tool_calls",
        "error_count",
        "model_invocation_proxy",
    )
    metrics = [
        metric
        for metric in candidate_metrics
        if all(
            _has_metric(baseline, metric) and _has_metric(engram, metric)
            for baseline, engram in pairs
        )
    ]
    intervals: dict[str, dict[str, float]] = {}
    randomization_p: dict[str, float] = {}
    for index, metric in enumerate(metrics):
        deltas = _metric_deltas(pairs, metric)
        interval = paired_bootstrap_interval(deltas, seed=seed + index)
        intervals[metric] = asdict(interval)
        randomization_p[metric] = paired_sign_flip_p_value(deltas, seed=seed + index)

    completion_deltas = [
        float(bool(engram["completed"])) - float(bool(baseline["completed"]))
        for baseline, engram in pairs
    ]
    completion_interval = paired_bootstrap_interval(completion_deltas, seed=seed + 30)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "complete_pairs": len(pairs),
        "primary_endpoint": {
            "name": "paired_task_completion_difference",
            "baseline_completed": sum(bool(item[0]["completed"]) for item in pairs),
            "engram_completed": sum(bool(item[1]["completed"]) for item in pairs),
            "engram_minus_baseline": asdict(completion_interval),
            "baseline_only_success": baseline_only,
            "engram_only_success": engram_only,
            "mcnemar_exact_p": exact_mcnemar_p_value(baseline_only, engram_only),
        },
        "secondary_endpoints": {
            metric: {
                "engram_minus_baseline": intervals[metric],
                "paired_sign_flip_p": randomization_p[metric],
            }
            for metric in intervals
        },
        "measurement_limits": {
            "actual_billed_usd": "unavailable for Codex subscription runs",
            "retry_count": "null unless a retry is observable in the host event stream",
            "model_invocation_proxy": "one visible codex exec session, not provider-internal calls",
            "context_consumption": "reported input_tokens; Codex reports cumulative usage",
        },
        "interpretation_guard": (
            "Pilot results estimate feasibility and variance. Confirmatory claims require the "
            "preregistered target sample, locked exclusions, and the official benchmark graders."
        ),
    }


def write_analysis(output_dir: Path, analysis: dict[str, Any]) -> None:
    (output_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    primary = analysis["primary_endpoint"]
    interval = primary["engram_minus_baseline"]
    lines = [
        "# Engram paired benchmark analysis",
        "",
        f"Generated: {analysis['generated_at']}",
        f"Complete ON/OFF pairs: {analysis['complete_pairs']}",
        "",
        "## Primary endpoint",
        "",
        (
            f"Completion: baseline {primary['baseline_completed']}/{analysis['complete_pairs']}; "
            f"Engram {primary['engram_completed']}/{analysis['complete_pairs']}."
        ),
        (
            "Paired difference Engram - baseline: "
            f"{interval['estimate']:+.3f} "
            f"(bootstrap 95% CI {interval['lower']:+.3f} to {interval['upper']:+.3f})."
        ),
        f"Exact McNemar p-value: {primary['mcnemar_exact_p']:.6f}.",
        "",
        "## Secondary endpoints",
        "",
        "| Metric | Mean paired delta | Bootstrap 95% CI | Sign-flip p |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric, result in analysis["secondary_endpoints"].items():
        estimate = result["engram_minus_baseline"]
        lines.append(
            f"| {metric} | {estimate['estimate']:+.6f} | "
            f"[{estimate['lower']:+.6f}, {estimate['upper']:+.6f}] | "
            f"{result['paired_sign_flip_p']:.6f} |"
        )
    lines.extend(["", f"> {analysis['interpretation_guard']}", ""])
    (output_dir / "analysis.md").write_text("\n".join(lines), encoding="utf-8")


def resolve_paths(root: Path, protocol_path: Path | None) -> tuple[Path, dict[str, Any]]:
    path = protocol_path or root / "benchmarks" / "scientific" / "protocol.json"
    return path, load_json(path)


def create_plan(
    root: Path,
    protocol: dict[str, Any],
    repetitions: int,
    *,
    model_filters: list[str] | None = None,
    task_filters: list[str] | None = None,
) -> list[PlannedRun]:
    tasks_path = root / protocol["task_source"]["path"]
    tasks = load_tasks(tasks_path)
    models = list(protocol["models"])
    if model_filters:
        unknown_models = set(model_filters) - set(models)
        if unknown_models:
            raise ValueError(f"Unknown models: {', '.join(sorted(unknown_models))}")
        models = [model for model in models if model in model_filters]
    if task_filters:
        unknown_tasks = set(task_filters) - {task.id for task in tasks}
        if unknown_tasks:
            raise ValueError(f"Unknown task IDs: {', '.join(sorted(unknown_tasks))}")
        tasks = [task for task in tasks if task.id in task_filters]
    return build_plan(
        tasks=tasks,
        models=models,
        reasoning_effort=protocol["design"]["reasoning_effort"],
        repetitions=repetitions,
        seed=int(protocol["design"]["random_seed"]),
        task_family=protocol["task_source"]["family"],
    )


def run_plan(
    *,
    root: Path,
    protocol: dict[str, Any],
    plan: list[PlannedRun],
    output_dir: Path,
    max_pairs: int | None,
    timeout_seconds: int,
) -> None:
    source_snapshot = ensure_study_lock(root=root, protocol=protocol, output_dir=output_dir)
    selected = select_complete_pairs(plan, max_pairs)
    plan_rows = [asdict(item) for item in plan]
    plan_path = output_dir / "plan.jsonl"
    if plan_path.exists() and read_jsonl(plan_path) != plan_rows:
        raise RuntimeError("Run plan changed after the study was locked")
    write_jsonl(plan_path, plan_rows)
    results_path = output_dir / "results.jsonl"
    completed_pairs = completed_pair_ids(read_jsonl(results_path))
    failures_path = output_dir / "failures.jsonl"
    tasks = {
        task.id: task for task in load_tasks(root / protocol["task_source"]["path"])
    }
    prices = load_prices(root / protocol["pricing_manifest"])
    workspace_slug = f"{protocol['study_id']}-{protocol['design']['random_seed']}"
    seed_path = output_dir / "memory-seed.json"
    if any(item.condition == "engram" for item in selected) and not seed_path.exists():
        seconds = seed_memory(list(tasks.values()), workspace_slug)
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text(
            json.dumps({"seconds": seconds, "workspace": workspace_slug}, indent=2) + "\n",
            encoding="utf-8",
        )
    for pair in ordered_plan_pairs(selected):
        pair_id = pair[0].pair_id
        if pair_id in completed_pairs:
            continue
        pair_records: list[dict[str, Any]] = []
        for item in pair:
            capture_key = hashlib.sha256(item.run_id.encode("utf-8")).hexdigest()[:12]
            capture_dir = output_dir / "r" / capture_key
            if capture_dir.exists():
                resolved_capture = capture_dir.resolve()
                resolved_runs = (output_dir / "r").resolve()
                if resolved_runs not in resolved_capture.parents:
                    raise RuntimeError(f"Refusing to reset capture outside {resolved_runs}")
                shutil.rmtree(resolved_capture)
            result = run_codex(
                root=root,
                task=tasks[item.task_id],
                mode=item.condition,
                model=item.model,
                reasoning_effort=item.reasoning_effort,
                workspace_slug=workspace_slug,
                timeout_seconds=timeout_seconds,
                capture_dir=capture_dir,
                snapshot_name="w",
                snapshot_source_root=source_snapshot,
            )
            pair_records.append(result_record(item, result, prices[item.model]))
            if result.exit_code != 0:
                failed_at = datetime.now(UTC).isoformat()
                append_jsonl_batch(
                    failures_path,
                    [
                        {
                            "failed_at": failed_at,
                            "failure_scope": "pair_aborted",
                            "trigger_run_id": item.run_id,
                            "record": record,
                        }
                        for record in pair_records
                    ],
                )
                raise RuntimeError(
                    f"Infrastructure failure in {item.run_id} (exit {result.exit_code}). "
                    f"The pair was excluded and recorded in {failures_path}."
                )
        append_jsonl_batch(results_path, pair_records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the paired Engram scientific benchmark")
    parser.add_argument("command", choices=("plan", "run", "analyze"))
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--max-pairs", type=int)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=600)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    _, protocol = resolve_paths(root, args.protocol)
    repetitions = args.repetitions or int(protocol["design"]["pilot_repetitions"])
    output_dir = args.output_dir or root / "artifacts" / "scientific" / protocol["study_id"]
    if args.command == "analyze":
        analysis = analyze_rows(
            read_jsonl(output_dir / "results.jsonl"),
            seed=int(protocol["design"]["random_seed"]),
        )
        write_analysis(output_dir, analysis)
        print(output_dir / "analysis.md")
        return
    plan = create_plan(
        root,
        protocol,
        repetitions,
        model_filters=args.model,
        task_filters=args.task_id,
    )
    if args.command == "plan":
        write_jsonl(output_dir / "plan.jsonl", [asdict(item) for item in plan])
        print(
            json.dumps(
                {
                    "pairs": len(plan) // 2,
                    "runs": len(plan),
                    "models": len(protocol["models"]),
                    "repetitions": repetitions,
                    "path": str(output_dir / "plan.jsonl"),
                }
            )
        )
        return
    run_plan(
        root=root,
        protocol=protocol,
        plan=plan,
        output_dir=output_dir,
        max_pairs=args.max_pairs,
        timeout_seconds=args.timeout,
    )
    print(output_dir)


if __name__ == "__main__":
    main()
