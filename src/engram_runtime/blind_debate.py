from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .scientific_evaluation import load_json, read_jsonl, write_jsonl


def build_blind_labels(rows: list[dict[str, Any]], *, seed: int) -> dict[str, str]:
    models = sorted({str(row["model"]) for row in rows})
    shuffled = list(models)
    random.Random(seed).shuffle(shuffled)
    return {model: f"Response {chr(65 + index)}" for index, model in enumerate(shuffled)}


def rotate_answers(
    answers: dict[str, str], *, judge_index: int
) -> list[tuple[str, str]]:
    ordered = sorted(answers.items())
    offset = judge_index % len(ordered) if ordered else 0
    return ordered[offset:] + ordered[:offset]


def build_debate_prompt(
    *,
    question: str,
    answers: list[tuple[str, str]],
    objective_scores: dict[str, float],
) -> str:
    blocks = "\n\n".join(f"## {label}\n{answer}" for label, answer in answers)
    score_lines = "\n".join(
        f"- {label}: objective coverage {score:.3f}"
        for label, score in sorted(objective_scores.items())
    )
    return f"""You are one member of a blinded evaluation jury.
Do not use tools, browse, or inspect local files. Judge only the supplied material.
The response labels are randomized and reveal no model identity.

Question:
{question}

Candidate responses:
{blocks}

Objective grader observations (primary evidence, never override them):
{score_lines}

Apply the same rubric to every response: factual accuracy 45%, direct support and citations
25%, completeness 20%, and efficiency 10%. Identify unsupported claims and material
omissions. Return only valid JSON with this exact shape:
{{"ranking":[{{"label":"Response A","score":0,"critique":"concise reason"}}],
"best_label":"Response A","confidence":0.0}}
Include every label exactly once. Scores are integers from 0 to 100. Confidence is 0 to 1.
This verdict is a secondary diagnostic and cannot replace the objective grader.
"""


def parse_json_answer(answer: str) -> dict[str, Any]:
    stripped = answer.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("judge answer did not contain a JSON object")
    payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("judge answer must be a JSON object")
    return payload


def run_judge(
    *,
    root: Path,
    model: str,
    reasoning_effort: str,
    prompt: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--approve-for-me",
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--cd",
        str(root),
        prompt,
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = time.perf_counter() - started
    answer = ""
    usage: dict[str, int] = {}
    errors: list[str] = []
    tool_ids: set[str] = set()
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            answer = str(item.get("text", answer))
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
        if item.get("type") in {"command_execution", "mcp_tool_call", "tool_call"}:
            tool_ids.add(str(item.get("id") or len(tool_ids)))
        if event.get("type") in {"error", "turn.failed"}:
            errors.append(str(event.get("message") or event.get("error") or event))
    verdict: dict[str, Any] | None = None
    if completed.returncode == 0:
        try:
            verdict = parse_json_answer(answer)
        except (ValueError, json.JSONDecodeError) as error:
            errors.append(str(error))
    if tool_ids:
        verdict = None
        errors.append("judge used tools despite the blind no-tool condition")
    if completed.returncode and completed.stderr.strip():
        errors.append(completed.stderr.strip()[-1_000:])
    return {
        "judge_model": model,
        "elapsed_seconds": round(elapsed, 3),
        "exit_code": completed.returncode,
        "usage": usage,
        "tool_calls": len(tool_ids),
        "verdict": verdict,
        "error": "\n".join(errors),
    }


def validate_verdict(verdict: dict[str, Any], labels: set[str]) -> None:
    ranking = verdict.get("ranking")
    if not isinstance(ranking, list):
        raise ValueError("ranking must be a list")
    returned_labels = {item.get("label") for item in ranking if isinstance(item, dict)}
    if returned_labels != labels or len(ranking) != len(labels):
        raise ValueError("ranking must include every blind label exactly once")
    for item in ranking:
        score = item.get("score")
        if not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("ranking scores must be integers from 0 to 100")
    if verdict.get("best_label") not in labels:
        raise ValueError("best_label must be one of the blind labels")


def aggregate_debate(
    *,
    jury_rows: list[dict[str, Any]],
    labels_by_model: dict[str, str],
    objective_scores: dict[str, float],
) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    labels = set(labels_by_model.values())
    for row in jury_rows:
        verdict = row.get("verdict")
        try:
            if not isinstance(verdict, dict):
                raise ValueError(row.get("error") or "missing verdict")
            validate_verdict(verdict, labels)
            valid.append(row)
        except ValueError as error:
            invalid.append({"judge_model": row["judge_model"], "reason": str(error)})
    scores: dict[str, list[int]] = defaultdict(list)
    best_counts: Counter[str] = Counter()
    for row in valid:
        verdict = row["verdict"]
        best_counts[verdict["best_label"]] += 1
        for item in verdict["ranking"]:
            scores[item["label"]].append(item["score"])
    reverse = {label: model for model, label in labels_by_model.items()}
    ranking = sorted(
        (
            {
                "label": label,
                "model": reverse[label],
                "mean_jury_score": sum(values) / len(values) if values else None,
                "jury_first_place_votes": best_counts[label],
                "objective_score": objective_scores[label],
            }
            for label, values in scores.items()
        ),
        key=lambda item: (item["mean_jury_score"], item["jury_first_place_votes"]),
        reverse=True,
    )
    winning_votes = max(best_counts.values(), default=0)
    disagreement = 1 - winning_votes / len(valid) if valid else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "valid_judges": len(valid),
        "invalid_judges": invalid,
        "jury_disagreement_rate": disagreement,
        "ranking": ranking,
        "claim_boundary": (
            "Blinded jury scores are secondary diagnostics. Objective completion and "
            "benchmark graders remain primary."
        ),
    }


def write_report(output_dir: Path, aggregate: dict[str, Any]) -> None:
    (output_dir / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Blind multi-model jury",
        "",
        f"Valid judges: {aggregate['valid_judges']}",
        f"Jury disagreement rate: {aggregate['jury_disagreement_rate']}",
        "",
        "| Model revealed after judging | Mean jury score | First-place votes | Objective score |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in aggregate["ranking"]:
        lines.append(
            f"| {item['model']} | {item['mean_jury_score']:.2f} | "
            f"{item['jury_first_place_votes']} | {item['objective_score']:.3f} |"
        )
    lines.extend(["", f"> {aggregate['claim_boundary']}", ""])
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a blind multi-model critique jury")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--condition", choices=("baseline", "engram"), default="engram")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--reasoning", default="high")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-judges", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    protocol = load_json(
        args.protocol or root / "benchmarks" / "scientific" / "protocol.json"
    )
    source_rows = [
        row
        for row in read_jsonl(args.input)
        if row["task_id"] == args.task_id and row["condition"] == args.condition
    ]
    models = list(protocol["models"])
    by_model = {row["model"]: row for row in source_rows}
    missing = set(models) - set(by_model)
    if missing:
        raise SystemExit(f"Missing independent answers for: {', '.join(sorted(missing))}")
    seed = int(protocol["design"]["random_seed"])
    labels_by_model = build_blind_labels(source_rows, seed=seed)
    answers = {
        labels_by_model[model]: by_model[model]["run"]["answer"] for model in models
    }
    objective_scores = {
        labels_by_model[model]: float(by_model[model]["score"]) for model in models
    }
    task = next(
        item
        for item in json.loads(
            (root / protocol["task_source"]["path"]).read_text(encoding="utf-8")
        )
        if item["id"] == args.task_id
    )
    judges = models[: args.max_judges] if args.max_judges else models
    plan = []
    for index, judge in enumerate(judges):
        ordered = rotate_answers(answers, judge_index=index)
        plan.append(
            {
                "judge_model": judge,
                "blind_order": [label for label, _ in ordered],
                "prompt": build_debate_prompt(
                    question=task["question"],
                    answers=ordered,
                    objective_scores=objective_scores,
                ),
            }
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        args.output_dir / "plan.jsonl",
        [
            {"judge_model": item["judge_model"], "blind_order": item["blind_order"]}
            for item in plan
        ],
    )
    if args.dry_run:
        print(args.output_dir / "plan.jsonl")
        return
    results_path = args.output_dir / "jury.jsonl"
    completed = {row["judge_model"] for row in read_jsonl(results_path)}
    for item in plan:
        if item["judge_model"] in completed:
            continue
        result = run_judge(
            root=root,
            model=item["judge_model"],
            reasoning_effort=args.reasoning,
            prompt=item["prompt"],
            timeout_seconds=args.timeout,
        )
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
    aggregate = aggregate_debate(
        jury_rows=read_jsonl(results_path),
        labels_by_model=labels_by_model,
        objective_scores=objective_scores,
    )
    write_report(args.output_dir, aggregate)
    print(args.output_dir / "report.md")


if __name__ == "__main__":
    main()
