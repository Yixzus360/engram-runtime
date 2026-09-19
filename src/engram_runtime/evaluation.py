from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .config import RuntimeSettings
from .mcp_server import EngramMemoryService

Mode = Literal["baseline", "engram"]


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    question: str
    expected_terms: list[str]
    memory: str


@dataclass
class RunResult:
    task_id: str
    mode: Mode
    model: str
    reasoning_effort: str
    elapsed_seconds: float
    exit_code: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    tool_calls: int
    expected_terms_found: int
    expected_terms_total: int
    answer: str
    error: str = ""

    @property
    def score(self) -> float:
        if not self.expected_terms_total:
            return 1.0
        return self.expected_terms_found / self.expected_terms_total

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cached_input_tokens, 0)


def load_tasks(path: Path) -> list[BenchmarkTask]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [BenchmarkTask(**item) for item in payload]


def parse_codex_jsonl(
    text: str,
    *,
    task: BenchmarkTask,
    mode: Mode,
    model: str,
    reasoning_effort: str,
    elapsed_seconds: float,
    exit_code: int,
    stderr: str = "",
) -> RunResult:
    usage: dict[str, int] = {}
    answer = ""
    tool_ids: set[str] = set()
    errors: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"non-JSON output: {line[:200]}")
            continue
        event_type = event.get("type", "")
        if event_type == "turn.completed":
            usage = event.get("usage") or {}
        item = event.get("item") or {}
        item_type = item.get("type", "")
        if event_type == "item.completed" and item_type == "agent_message":
            answer = item.get("text", answer)
        if item_type in {"command_execution", "mcp_tool_call", "tool_call"}:
            tool_ids.add(str(item.get("id") or f"{event_type}:{len(tool_ids)}"))
        if event_type in {"error", "turn.failed"}:
            errors.append(str(event.get("message") or event.get("error") or event))
    lowered = answer.casefold()
    matched = sum(
        any(option.casefold() in lowered for option in term.split("|"))
        for term in task.expected_terms
    )
    if stderr.strip() and exit_code:
        errors.append(stderr.strip()[-1_000:])
    return RunResult(
        task_id=task.id,
        mode=mode,
        model=model,
        reasoning_effort=reasoning_effort,
        elapsed_seconds=round(elapsed_seconds, 3),
        exit_code=exit_code,
        input_tokens=int(usage.get("input_tokens", 0)),
        cached_input_tokens=int(usage.get("cached_input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        reasoning_output_tokens=int(usage.get("reasoning_output_tokens", 0)),
        tool_calls=len(tool_ids),
        expected_terms_found=matched,
        expected_terms_total=len(task.expected_terms),
        answer=answer,
        error="\n".join(errors),
    )


def build_codex_command(
    *,
    workspace: Path,
    server_root: Path,
    task: BenchmarkTask,
    mode: Mode,
    model: str,
    reasoning_effort: str,
    workspace_slug: str,
) -> tuple[list[str], str]:
    prompt_lines = [
        "This is a read-only benchmark. Do not modify files or persistent state.",
        "Inspect only the minimum repository evidence needed for a correct answer.",
    ]
    if mode == "engram":
        prompt_lines.extend(
            [
                (
                    "Call engram.recall_signals exactly once with the task and limit=1 before "
                    "inspecting files."
                ),
                (
                    "Use recalled signals only as leads and verify the decisive claim in "
                    "current files."
                ),
            ]
        )
    prompt_lines.append(f"Task: {task.question}")
    prompt = "\n".join(prompt_lines)
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
        str(workspace),
    ]
    if mode == "engram":
        encoded_root = json.dumps(str(server_root))
        encoded_workspace = json.dumps(workspace_slug)
        command.extend(
            [
                "--config",
                'mcp_servers.engram.command="uv"',
                "--config",
                'mcp_servers.engram.args=["run","engram-mcp"]',
                "--config",
                f"mcp_servers.engram.cwd={encoded_root}",
                "--config",
                "mcp_servers.engram.startup_timeout_sec=30",
                "--config",
                (
                    "mcp_servers.engram.env="
                    f"{{ENGRAM_WORKSPACE_SLUG={encoded_workspace}}}"
                ),
                "--config",
                'mcp_servers.engram.enabled_tools=["recall_signals"]',
            ]
        )
    command.append(prompt)
    return command, prompt


def prepare_snapshot(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for directory in ("src", "docs"):
        shutil.copytree(root / directory, destination / directory)
    for filename in ("README.md", "pyproject.toml", "LICENSE"):
        shutil.copy2(root / filename, destination / filename)


def run_codex(
    *,
    root: Path,
    task: BenchmarkTask,
    mode: Mode,
    model: str,
    reasoning_effort: str,
    workspace_slug: str,
    timeout_seconds: int,
    capture_dir: Path,
) -> RunResult:
    snapshot = capture_dir / "workspaces" / f"{task.id}-{mode}"
    prepare_snapshot(root, snapshot)
    command, _ = build_codex_command(
        workspace=snapshot,
        server_root=root,
        task=task,
        mode=mode,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace_slug=workspace_slug,
    )
    environment = os.environ.copy()
    environment["ENGRAM_WORKSPACE_SLUG"] = workspace_slug
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        elapsed = time.perf_counter() - started
        capture_dir.mkdir(parents=True, exist_ok=True)
        (capture_dir / f"{task.id}-{mode}.jsonl").write_text(
            completed.stdout,
            encoding="utf-8",
        )
        (capture_dir / f"{task.id}-{mode}.stderr.log").write_text(
            completed.stderr,
            encoding="utf-8",
        )
        return parse_codex_jsonl(
            completed.stdout,
            task=task,
            mode=mode,
            model=model,
            reasoning_effort=reasoning_effort,
            elapsed_seconds=elapsed,
            exit_code=completed.returncode,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.perf_counter() - started
        output = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else ""
        capture_dir.mkdir(parents=True, exist_ok=True)
        (capture_dir / f"{task.id}-{mode}.jsonl").write_text(
            output or "",
            encoding="utf-8",
        )
        return parse_codex_jsonl(
            output or "",
            task=task,
            mode=mode,
            model=model,
            reasoning_effort=reasoning_effort,
            elapsed_seconds=elapsed,
            exit_code=124,
            stderr=f"Timed out after {timeout_seconds} seconds",
        )


def seed_memory(tasks: list[BenchmarkTask], workspace_slug: str) -> float:
    started = time.perf_counter()
    settings = RuntimeSettings(workspace_slug=workspace_slug)
    service = EngramMemoryService.open(settings)
    try:
        for task in tasks:
            service.preserve(
                kind="fact",
                content=task.memory,
                task=task.question,
                evidence="Verified against the repository paths named in this signal.",
                success=True,
                confidence=1.0,
            )
    finally:
        service.close()
    return time.perf_counter() - started


def write_report(
    output_dir: Path,
    results: list[RunResult],
    *,
    seed_seconds: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "results.jsonl"
    raw_path.write_text(
        "".join(json.dumps(asdict(result), ensure_ascii=False) + "\n" for result in results),
        encoding="utf-8",
    )
    lines = [
        "# Codex + Engram benchmark",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Local memory seed time: {seed_seconds:.3f}s (reported separately from inference)",
        "",
        "| Task | Mode | Input | Cached | Uncached | Output | Seconds | Tools | Score | Exit |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| {result.task_id} | {result.mode} | {result.input_tokens} | "
            f"{result.cached_input_tokens} | {result.uncached_input_tokens} | "
            f"{result.output_tokens} | "
            f"{result.elapsed_seconds:.3f} | {result.tool_calls} | "
            f"{result.expected_terms_found}/{result.expected_terms_total} | "
            f"{result.exit_code} |"
        )
    pairs: dict[str, dict[str, RunResult]] = {}
    for result in results:
        pairs.setdefault(result.task_id, {})[result.mode] = result
    lines.extend(["", "## Paired deltas", ""])
    for task_id, pair in pairs.items():
        if {"baseline", "engram"} <= pair.keys():
            baseline = pair["baseline"]
            engram = pair["engram"]
            lines.append(
                f"- **{task_id}:** input {engram.input_tokens - baseline.input_tokens:+d}, "
                f"uncached {engram.uncached_input_tokens - baseline.uncached_input_tokens:+d}, "
                f"output {engram.output_tokens - baseline.output_tokens:+d}, "
                f"time {engram.elapsed_seconds - baseline.elapsed_seconds:+.3f}s, "
                f"score {engram.score - baseline.score:+.2f}."
            )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Codex with and without Engram MCP")
    parser.add_argument("--mode", choices=("baseline", "engram", "both"), default="both")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--reasoning", default="low")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--workspace", default="codex-benchmark-v1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    tasks = load_tasks(root / "benchmarks" / "codex" / "tasks.json")
    if args.task_id:
        wanted = set(args.task_id)
        tasks = [task for task in tasks if task.id in wanted]
        missing = wanted - {task.id for task in tasks}
        if missing:
            raise SystemExit(f"Unknown task IDs: {', '.join(sorted(missing))}")
    modes: tuple[Mode, ...] = (
        ("baseline", "engram") if args.mode == "both" else (args.mode,)
    )
    if args.dry_run:
        for task in tasks:
            for mode in modes:
                command, prompt = build_codex_command(
                    workspace=root,
                    server_root=root,
                    task=task,
                    mode=mode,
                    model=args.model,
                    reasoning_effort=args.reasoning,
                    workspace_slug=args.workspace,
                )
                print(json.dumps({"task": task.id, "mode": mode, "command": command[:-1]}))
                print(prompt)
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or root / "artifacts" / "benchmarks" / stamp
    seed_seconds = seed_memory(tasks, args.workspace) if "engram" in modes else 0.0
    results = [
        run_codex(
            root=root,
            task=task,
            mode=mode,
            model=args.model,
            reasoning_effort=args.reasoning,
            workspace_slug=args.workspace,
            timeout_seconds=args.timeout,
            capture_dir=output_dir / "events",
        )
        for task in tasks
        for mode in modes
    ]
    write_report(output_dir, results, seed_seconds=seed_seconds)
    print(output_dir)


if __name__ == "__main__":
    main()
