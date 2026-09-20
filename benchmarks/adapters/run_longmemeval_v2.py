from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COMMIT = "2cc8c540bdb87fe6761629b585e727e1c4704520"
LONGMEMEVAL_ROOT = Path(
    os.environ.get(
        "LONGMEMEVAL_V2_ROOT",
        PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2",
    )
).resolve()


def verify_checkout(root: Path) -> None:
    if not (root / "evaluation" / "harness.py").exists():
        raise SystemExit(
            "LongMemEval-V2 checkout not found. Set LONGMEMEVAL_V2_ROOT to the pinned clone."
        )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if commit != EXPECTED_COMMIT:
        raise SystemExit(
            f"LongMemEval-V2 commit mismatch: expected {EXPECTED_COMMIT}, found {commit}"
        )


def _argument_value(name: str) -> str | None:
    try:
        return sys.argv[sys.argv.index(name) + 1]
    except (ValueError, IndexError):
        return None


def _gpu_snapshot() -> dict[str, object] | None:
    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    fields = [part.strip() for part in output.splitlines()[0].split(",")]
    if len(fields) != 5:
        return {"raw": output}
    return {
        "name": fields[0],
        "memory_total_mib": int(fields[1]),
        "memory_used_mib": int(fields[2]),
        "memory_free_mib": int(fields[3]),
        "utilization_percent": int(fields[4]),
    }


def _extract_message_text(message_content: object) -> str:
    if isinstance(message_content, str):
        return message_content.strip()
    if isinstance(message_content, list):
        text_parts = []
        for item in message_content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        joined = "\n".join(text_parts).strip()
        if joined:
            return joined
    raise ValueError("Evaluator model returned empty response content.")


def install_evaluator_budget(qa_eval_metrics: Any) -> None:
    from benchmarks.adapters.longmemeval_budget import (
        EvaluatorBudget,
        EvaluatorPricing,
    )

    usage_path = Path(
        os.environ.get(
            "ENGRAM_LME_EVALUATOR_USAGE_LOG",
            PROJECT_ROOT / "artifacts" / "official" / "LongMemEval-V2" / "evaluator-usage.jsonl",
        )
    ).resolve()
    budget = EvaluatorBudget(
        usage_path,
        maximum_usd=float(os.environ.get("ENGRAM_LME_EVALUATOR_MAX_USD", "30")),
        pricing=EvaluatorPricing(
            input_per_million=float(
                os.environ.get("ENGRAM_LME_EVALUATOR_INPUT_PER_MILLION", "1.75")
            ),
            cached_input_per_million=float(
                os.environ.get("ENGRAM_LME_EVALUATOR_CACHED_INPUT_PER_MILLION", "0.175")
            ),
            output_per_million=float(
                os.environ.get("ENGRAM_LME_EVALUATOR_OUTPUT_PER_MILLION", "14")
            ),
        ),
    )
    qa_eval_metrics.OPENAI_MAX_RETRIES = 0

    if os.environ.get("ENGRAM_LME_EVALUATOR_TRANSPORT") == "opencode":
        log_lock = threading.Lock()

        def append_oauth_usage(payload: dict[str, Any]) -> None:
            usage_path.parent.mkdir(parents=True, exist_ok=True)
            with log_lock, usage_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

        def oauth_call_chat_completion(
            *,
            client: Any,
            model: str,
            messages: list[dict[str, str]],
            max_completion_tokens: int,
            reasoning_effort: str | None,
            temperature: float | None,
            top_p: float | None,
            timeout_seconds: float,
        ) -> str:
            del client, max_completion_tokens, temperature, top_p
            from benchmarks.adapters.opencode_longmemeval_reader import (
                call_opencode_reader,
            )

            call_id = hashlib.sha256(
                (datetime.now(UTC).isoformat() + json.dumps(messages, sort_keys=True)).encode()
            ).hexdigest()[:24]
            try:
                text, usage = call_opencode_reader(
                    messages,
                    model=model,
                    variant=reasoning_effort or "medium",
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                append_oauth_usage(
                    {
                        "call_id": call_id,
                        "status": "failed_oauth",
                        "transport": "opencode_cli_chatgpt_oauth",
                        "requested_model": model,
                        "error_type": type(exc).__name__,
                        "timestamp_utc": datetime.now(UTC).isoformat(),
                    }
                )
                raise
            append_oauth_usage(
                {
                    "call_id": call_id,
                    "status": "settled_oauth",
                    "transport": "opencode_cli_chatgpt_oauth",
                    "requested_model": model,
                    "requested_variant": reasoning_effort or "medium",
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
                    "cached_input_tokens": int(usage.get("cached_input_tokens", 0)),
                    "reported_cost_usd": float(usage.get("reported_cost_usd", 0.0)),
                    "opencode_session_id": usage.get("opencode_session_id"),
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                }
            )
            return text

        qa_eval_metrics._call_chat_completion = oauth_call_chat_completion
        return

    def budgeted_call_chat_completion(
        *,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        max_completion_tokens: int,
        reasoning_effort: str | None,
        temperature: float | None,
        top_p: float | None,
        timeout_seconds: float,
    ) -> str:
        call_id, reserved_usd = budget.reserve(
            model=model,
            messages=messages,
            max_completion_tokens=max_completion_tokens,
        )
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "timeout": timeout_seconds,
        }
        if reasoning_effort is not None:
            request["reasoning_effort"] = reasoning_effort
        if temperature is not None:
            request["temperature"] = temperature
        if top_p is not None:
            request["top_p"] = top_p
        try:
            response = client.chat.completions.create(**request)
        except Exception as exc:
            budget.fail(
                call_id,
                model=model,
                reserved_usd=reserved_usd,
                error_type=type(exc).__name__,
            )
            raise
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = int(getattr(prompt_details, "cached_tokens", 0) or 0)
        budget.settle(
            call_id,
            model=model,
            resolved_model=str(getattr(response, "model", model)),
            input_tokens=prompt_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=completion_tokens,
            reserved_usd=reserved_usd,
        )
        return _extract_message_text(response.choices[0].message.content)

    qa_eval_metrics._call_chat_completion = budgeted_call_chat_completion


def install_runtime_telemetry(harness: Any, memory_classes: list[type[Any]]) -> None:
    for memory_class in memory_classes:
        original_insert = memory_class.insert
        original_query = memory_class.query
        original_post_query = memory_class.post_query_hook

        def timed_insert(
            self: Any,
            trajectory: dict[str, object],
            _original: Any = original_insert,
        ) -> None:
            started = time.perf_counter()
            try:
                _original(self, trajectory)
            finally:
                self._engram_index_seconds = getattr(self, "_engram_index_seconds", 0.0) + (
                    time.perf_counter() - started
                )
                self._engram_index_calls = getattr(self, "_engram_index_calls", 0) + 1

        def timed_query(
            self: Any,
            query: str,
            query_image: str | None = None,
            _original: Any = original_query,
        ) -> Any:
            started = time.perf_counter()
            try:
                return _original(self, query, query_image=query_image)
            finally:
                self._engram_query_seconds = getattr(self, "_engram_query_seconds", 0.0) + (
                    time.perf_counter() - started
                )
                self._engram_query_calls = getattr(self, "_engram_query_calls", 0) + 1

        def telemetry_post_query(
            self: Any,
            *,
            query: str,
            query_image: str | None,
            memory_context: list[Any],
            _original: Any = original_post_query,
        ) -> dict[str, object]:
            existing = _original(
                self,
                query=query,
                query_image=query_image,
                memory_context=memory_context,
            )
            payload = dict(existing) if isinstance(existing, dict) else {}
            payload["engram_benchmark_telemetry"] = {
                "index_seconds": getattr(self, "_engram_index_seconds", 0.0),
                "index_calls": getattr(self, "_engram_index_calls", 0),
                "query_seconds": getattr(self, "_engram_query_seconds", 0.0),
                "query_calls": getattr(self, "_engram_query_calls", 0),
            }
            if hasattr(self, "_engram_rag_cache_hits"):
                payload["rag_embedding_cache"] = {
                    "hits": getattr(self, "_engram_rag_cache_hits", 0),
                    "misses": getattr(self, "_engram_rag_cache_misses", 0),
                    "miss_embedding_seconds": getattr(self, "_engram_rag_embedding_seconds", 0.0),
                }
            return payload

        memory_class.insert = timed_insert
        memory_class.query = timed_query
        memory_class.post_query_hook = telemetry_post_query

    original_reader_call = harness.call_reader_model_async

    async def timed_reader_call(client: Any, args: Any, messages: list[dict[str, Any]]) -> Any:
        started = time.perf_counter()
        if os.environ.get("ENGRAM_LME_READER_TRANSPORT") == "opencode":
            from benchmarks.adapters.opencode_longmemeval_reader import (
                call_opencode_reader_async,
            )

            text, usage = await call_opencode_reader_async(
                messages,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            text, usage = await original_reader_call(client, args, messages)
        usage["wall_seconds"] = time.perf_counter() - started
        return text, usage

    harness.call_reader_model_async = timed_reader_call

    original_build_extra_body = harness.build_extra_body

    def build_local_reader_extra_body(args: Any) -> dict[str, Any] | None:
        extra_body = dict(original_build_extra_body(args) or {})
        if args.base_url and args.model == "qwen3.5-9b":
            # Ollama needs its native flag to separate reasoning from final content.
            # This implements the official reader-enable-thinking setting; without
            # it the reasoning trace is returned as content and can loop to the cap.
            extra_body["think"] = bool(args.reader_enable_thinking)
        return extra_body or None

    harness.build_extra_body = build_local_reader_extra_body

    for memory_class in memory_classes:
        if memory_class.__name__ != "RagMemory":
            continue
        original_controller_request = memory_class._build_controller_request

        def build_local_controller_request(
            self: Any,
            messages: list[dict[str, Any]],
            _original: Any = original_controller_request,
            *,
            disable_thinking: bool,
            max_completion_tokens: int | None = None,
        ) -> dict[str, Any]:
            request = _original(
                self,
                messages,
                disable_thinking=disable_thinking,
                max_completion_tokens=max_completion_tokens,
            )
            if self.controller_base_url and self.controller_model == "qwen3.5-9b":
                extra_body = dict(request.get("extra_body") or {})
                extra_body["think"] = not disable_thinking
                request["extra_body"] = extra_body
            return request

        memory_class._build_controller_request = build_local_controller_request

        original_embed_texts = memory_class._embed_texts

        def cached_rag_embeddings(
            self: Any,
            texts: list[str],
            *,
            is_query: bool,
            _original: Any = original_embed_texts,
        ) -> Any:
            if not texts:
                return _original(self, texts, is_query=is_query)
            import numpy as np

            from benchmarks.adapters.longmemeval_vector_cache import (
                PersistentVectorCache,
            )

            namespace = f"{self.embedding_model}|{self.embedding_max_input_tokens}"
            cache = PersistentVectorCache(
                PROJECT_ROOT
                / "artifacts"
                / "official"
                / "LongMemEval-V2"
                / "rag-embedding-cache.sqlite3",
                namespace,
            )
            keys = [
                hashlib.sha256(
                    (
                        f"query={is_query}|instruction={self.embedding_query_instruction}|{text}"
                    ).encode()
                ).hexdigest()
                for text in texts
            ]
            cached = cache.get_many(keys)
            missing_positions = [
                index for index, cache_key in enumerate(keys) if cache_key not in cached
            ]
            if missing_positions:
                started = time.perf_counter()
                embedded = _original(
                    self,
                    [texts[index] for index in missing_positions],
                    is_query=is_query,
                )
                self._engram_rag_embedding_seconds = getattr(
                    self, "_engram_rag_embedding_seconds", 0.0
                ) + (time.perf_counter() - started)
                additions: dict[str, list[float]] = {}
                for index, vector in zip(missing_positions, embedded, strict=True):
                    values = [float(value) for value in vector]
                    cached[keys[index]] = values
                    additions[keys[index]] = values
                cache.put_many(additions)
            self._engram_rag_cache_hits = getattr(self, "_engram_rag_cache_hits", 0) + (
                len(texts) - len(missing_positions)
            )
            self._engram_rag_cache_misses = getattr(self, "_engram_rag_cache_misses", 0) + len(
                missing_positions
            )
            return np.asarray([cached[cache_key] for cache_key in keys], dtype=np.float32)

        memory_class._embed_texts = cached_rag_embeddings


def main() -> None:
    verify_checkout(LONGMEMEVAL_ROOT)
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(LONGMEMEVAL_ROOT))

    import evaluation.harness as harness
    import evaluation.qa_eval_metrics as qa_eval_metrics
    import evaluation.run_eval as run_eval
    from memory_modules.rag import RagMemory

    from benchmarks.adapters.engram_longmemeval_v2 import EngramLongMemEvalMemory

    install_evaluator_budget(qa_eval_metrics)
    install_runtime_telemetry(harness, [RagMemory, EngramLongMemEvalMemory])

    original_inject = harness.inject_runtime_memory_params

    def inject_engram_runtime(memory_config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        runtime = original_inject(memory_config, **kwargs)
        if runtime["memory_type"] == "engram_runtime":
            runtime["memory_params"]["workspace_dir"] = str(Path(kwargs["workspace_dir"]).resolve())
        return runtime

    harness.inject_runtime_memory_params = inject_engram_runtime
    harness.NONSHARED_PARALLEL_MEMORY_TYPES.add("engram_runtime")
    run_eval.METHODS.add("engram_runtime")
    original_build_memory_config = run_eval.build_memory_config

    def build_engram_config(args: Any, data_root: Path) -> dict[str, object]:
        if args.method != "engram_runtime":
            return original_build_memory_config(args, data_root)
        return {
            "memory_type": "engram_runtime",
            "memory_params": {
                "workspace_slug": "longmemeval-v2-engram",
                "top_k": 6,
                "maximum_chunk_characters": 3500,
                "batch_size": 64,
                "embedding_cache_path": str(
                    PROJECT_ROOT
                    / "artifacts"
                    / "official"
                    / "LongMemEval-V2"
                    / "engram-embedding-cache.sqlite3"
                ),
            },
        }

    run_eval.build_memory_config = build_engram_config
    output_dir_arg = _argument_value("--output-dir")
    output_dir = Path(output_dir_arg).resolve() if output_dir_arg else None
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    status = "completed"
    try:
        run_eval.main()
    except BaseException:
        status = "failed"
        raise
    finally:
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            telemetry = {
                "status": status,
                "started_at_utc": started_at,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "wall_seconds": time.perf_counter() - started,
                "reader_transport": os.environ.get(
                    "ENGRAM_LME_READER_TRANSPORT", "openai_compatible"
                ),
                "reader_model": _argument_value("--reader-model"),
                "reader_variant": (
                    "low" if os.environ.get("ENGRAM_LME_READER_TRANSPORT") == "opencode" else None
                ),
                "gpu_at_exit": _gpu_snapshot(),
                "evaluator_usage_log": os.environ.get(
                    "ENGRAM_LME_EVALUATOR_USAGE_LOG",
                    str(
                        PROJECT_ROOT
                        / "artifacts"
                        / "official"
                        / "LongMemEval-V2"
                        / "evaluator-usage.jsonl"
                    ),
                ),
            }
            (output_dir / "engram_run_telemetry.json").write_text(
                json.dumps(telemetry, indent=2) + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
