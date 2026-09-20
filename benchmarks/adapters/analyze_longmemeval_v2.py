from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = (
    PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2" / "opencode-astra-study"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "benchmarks" / "scientific" / "longmemeval-v2-results.json"
BOOTSTRAP_SEED = 20260920
BOOTSTRAP_SAMPLES = 100_000


@dataclass(frozen=True)
class RunSpec:
    label: str
    condition: str
    domain: str
    expected_rows: int


RUNS = (
    RunSpec("engram_off_web", "OFF", "web", 240),
    RunSpec("conventional_rag_web", "RAG", "web", 240),
    RunSpec("engram_on_web", "ON", "web", 240),
    RunSpec("engram_on_enterprise", "ON", "enterprise", 211),
    RunSpec("conventional_rag_enterprise", "RAG", "enterprise", 211),
    RunSpec("engram_off_enterprise", "OFF", "enterprise", 211),
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def is_llm_graded(row: dict[str, Any]) -> bool:
    return str(row.get("eval_function", "")).startswith("llm_")


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deterministic = [row for row in rows if not is_llm_graded(row)]
    llm = [row for row in rows if is_llm_graded(row)]
    usage = [row.get("usage") or {} for row in rows]

    def score_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        correct = sum(bool(row.get("score_bool")) for row in items)
        return {
            "questions": len(items),
            "correct": correct,
            "accuracy": correct / len(items) if items else None,
        }

    return {
        "all": score_summary(rows),
        "deterministic": score_summary(deterministic),
        "llm_judged": score_summary(llm),
        "unknown": sum(bool(row.get("is_unknown")) for row in rows),
        "unknown_rate": sum(bool(row.get("is_unknown")) for row in rows) / len(rows),
        "reader_usage": {
            "prompt_tokens": sum(int(item.get("prompt_tokens", 0) or 0) for item in usage),
            "completion_tokens": sum(int(item.get("completion_tokens", 0) or 0) for item in usage),
            "reasoning_tokens": sum(int(item.get("reasoning_tokens", 0) or 0) for item in usage),
            "wall_seconds_sum": sum(float(item.get("wall_seconds", 0.0) or 0.0) for item in usage),
        },
    }


def exact_mcnemar_p(gains: int, losses: int) -> float:
    discordant = gains + losses
    if discordant == 0:
        return 1.0
    smaller = min(gains, losses)
    lower_tail = sum(math.comb(discordant, index) for index in range(smaller + 1))
    return min(1.0, 2.0 * lower_tail / (2**discordant))


def paired_comparison(
    baseline: Iterable[dict[str, Any]],
    treatment: Iterable[dict[str, Any]],
    *,
    subset: str = "all",
) -> dict[str, Any]:
    def include(row: dict[str, Any]) -> bool:
        if subset == "deterministic":
            return not is_llm_graded(row)
        if subset == "llm_judged":
            return is_llm_graded(row)
        return True

    base = {
        str(row["question_id"]): bool(row.get("score_bool")) for row in baseline if include(row)
    }
    treat = {
        str(row["question_id"]): bool(row.get("score_bool")) for row in treatment if include(row)
    }
    if set(base) != set(treat):
        raise ValueError("Paired comparison question sets differ")
    question_ids = sorted(base)
    gains = sum(not base[item] and treat[item] for item in question_ids)
    losses = sum(base[item] and not treat[item] for item in question_ids)
    ties = len(question_ids) - gains - losses
    delta = (gains - losses) / len(question_ids)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.multinomial(
        len(question_ids),
        [losses / len(question_ids), ties / len(question_ids), gains / len(question_ids)],
        size=BOOTSTRAP_SAMPLES,
    )
    deltas = (draws[:, 2] - draws[:, 0]) / len(question_ids)
    interval = np.quantile(deltas, [0.025, 0.975])
    return {
        "subset": subset,
        "pairs": len(question_ids),
        "baseline_correct": sum(base.values()),
        "treatment_correct": sum(treat.values()),
        "baseline_accuracy": sum(base.values()) / len(question_ids),
        "treatment_accuracy": sum(treat.values()) / len(question_ids),
        "delta_accuracy": delta,
        "bootstrap_95_ci": [float(interval[0]), float(interval[1])],
        "gains": gains,
        "losses": losses,
        "ties": ties,
        "mcnemar_exact_two_sided_p": exact_mcnemar_p(gains, losses),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
    }


def relative_reduction(treatment: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("Cannot calculate a relative reduction from a zero baseline")
    return 1.0 - treatment / baseline


def analyze(artifact_root: Path) -> dict[str, Any]:
    by_run: dict[str, list[dict[str, Any]]] = {}
    run_summaries: dict[str, Any] = {}
    domain_sets: dict[str, list[set[str]]] = {"web": [], "enterprise": []}
    for spec in RUNS:
        run_dir = artifact_root / spec.label
        rows_path = run_dir / "per_question.jsonl"
        rows = read_jsonl(rows_path)
        if len(rows) != spec.expected_rows:
            raise ValueError(f"{spec.label}: expected {spec.expected_rows} rows, found {len(rows)}")
        question_ids = [str(row["question_id"]) for row in rows]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError(f"{spec.label}: duplicate question ids")
        for row in rows:
            usage = row.get("usage") or {}
            if usage.get("requested_model") != "gpt-6-astra":
                raise ValueError(f"{spec.label}: unexpected reader model")
            if usage.get("requested_variant") != "low":
                raise ValueError(f"{spec.label}: unexpected reader variant")
            if usage.get("transport") != "opencode_cli_chatgpt_oauth":
                raise ValueError(f"{spec.label}: unexpected reader transport")
        telemetry = json.loads((run_dir / "engram_run_telemetry.json").read_text(encoding="utf-8"))
        if telemetry.get("status") != "completed":
            raise ValueError(f"{spec.label}: telemetry is not completed")
        summary = summarize_rows(rows)
        metrics = json.loads((run_dir / "aggregated_metrics.json").read_text(encoding="utf-8"))
        summary.update(
            {
                "condition": spec.condition,
                "domain": spec.domain,
                "run_wall_seconds": float(telemetry["wall_seconds"]),
                "memory_context": metrics.get("memory_context"),
                "memory_query": metrics.get("memory_query"),
                "per_question_sha256": sha256(rows_path),
            }
        )
        by_run[spec.label] = rows
        run_summaries[spec.label] = summary
        domain_sets[spec.domain].append(set(question_ids))

    for domain, sets in domain_sets.items():
        if any(item != sets[0] for item in sets[1:]):
            raise ValueError(f"{domain}: condition question sets differ")

    by_condition: dict[str, list[dict[str, Any]]] = {"OFF": [], "RAG": [], "ON": []}
    for spec in RUNS:
        by_condition[spec.condition].extend(by_run[spec.label])
    condition_summaries = {
        condition: summarize_rows(rows) for condition, rows in by_condition.items()
    }
    for condition in condition_summaries:
        condition_summaries[condition]["run_wall_seconds"] = sum(
            run_summaries[spec.label]["run_wall_seconds"]
            for spec in RUNS
            if spec.condition == condition
        )

    on_usage = condition_summaries["ON"]["reader_usage"]
    rag_usage = condition_summaries["RAG"]["reader_usage"]
    efficiency = {
        "ON_vs_RAG": {
            "reader_prompt_token_reduction": relative_reduction(
                on_usage["prompt_tokens"], rag_usage["prompt_tokens"]
            ),
            "reader_completion_token_reduction": relative_reduction(
                on_usage["completion_tokens"], rag_usage["completion_tokens"]
            ),
            "run_wall_time_reduction": relative_reduction(
                condition_summaries["ON"]["run_wall_seconds"],
                condition_summaries["RAG"]["run_wall_seconds"],
            ),
        },
        "note": (
            "OFF has no retrieved memory, so token savings claims use the conventional RAG "
            "comparator rather than OFF."
        ),
    }

    comparisons: dict[str, Any] = {}
    for name, baseline, treatment in (
        ("ON_minus_OFF", "OFF", "ON"),
        ("RAG_minus_OFF", "OFF", "RAG"),
        ("ON_minus_RAG", "RAG", "ON"),
    ):
        comparisons[name] = {
            subset: paired_comparison(
                by_condition[baseline], by_condition[treatment], subset=subset
            )
            for subset in ("deterministic", "llm_judged", "all")
        }
        comparisons[name]["baseline"] = baseline
        comparisons[name]["treatment"] = treatment

    domain_comparisons: dict[str, Any] = {}
    for domain in ("web", "enterprise"):
        domain_rows = {
            condition: [
                row
                for spec in RUNS
                if spec.condition == condition and spec.domain == domain
                for row in by_run[spec.label]
            ]
            for condition in ("OFF", "RAG", "ON")
        }
        domain_comparisons[domain] = {
            "ON_minus_OFF": paired_comparison(domain_rows["OFF"], domain_rows["ON"]),
            "RAG_minus_OFF": paired_comparison(domain_rows["OFF"], domain_rows["RAG"]),
            "ON_minus_RAG": paired_comparison(domain_rows["RAG"], domain_rows["ON"]),
        }

    ledger = read_jsonl(artifact_root / "evaluator-usage.jsonl")
    settled = [row for row in ledger if row.get("status") == "settled_oauth"]
    failures = [row for row in ledger if row.get("status") == "failed_oauth"]
    llm_total = sum(summary["llm_judged"]["questions"] for summary in condition_summaries.values())
    deterministic_total = sum(
        summary["deterministic"]["questions"] for summary in condition_summaries.values()
    )
    if len(settled) != 468 or llm_total != 468:
        raise ValueError(
            f"Expected 468 settled OAuth and LLM rows, found {len(settled)} and {llm_total}"
        )
    if deterministic_total != 885:
        raise ValueError(f"Expected 885 deterministic rows, found {deterministic_total}")
    if sum(len(rows) for rows in by_run.values()) != 1353:
        raise ValueError("Expected 1,353 total rows")
    if any(float(row.get("reported_cost_usd", 0.0) or 0.0) != 0.0 for row in ledger):
        raise ValueError("Non-zero OAuth cost was reported")

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "benchmark": "LongMemEval-V2",
        "classification": (
            "Local controlled replication using the official small-tier dataset and grader "
            "prompts; not an official leaderboard submission"
        ),
        "reader": {
            "model": "gpt-6-astra",
            "variant": "low",
            "transport": "OpenCode ChatGPT OAuth",
        },
        "llm_judge": {
            "model": "gpt-5.5",
            "variant": "medium",
            "transport": "OpenCode ChatGPT OAuth",
        },
        "validation": {
            "complete_runs": len(RUNS),
            "responses": 1353,
            "questions_per_condition": 451,
            "deterministic_scores": deterministic_total,
            "llm_judgments": llm_total,
            "settled_oauth_ledger_records": len(settled),
            "historical_failed_oauth_records_excluded": len(failures),
            "reported_api_cost_usd": 0.0,
        },
        "runs": run_summaries,
        "conditions": condition_summaries,
        "comparisons": comparisons,
        "domain_comparisons": domain_comparisons,
        "efficiency": efficiency,
        "claim_boundary": (
            "The objective primary result is the deterministic subset. LLM-judged and combined "
            "scores are secondary. The result supports this fixed reader, dataset revision, and "
            "local implementation; it does not establish universal agent performance."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = analyze(args.artifact_root.resolve())
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["validation"], indent=2))


if __name__ == "__main__":
    main()
