from __future__ import annotations

import os
import subprocess
import sys
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


def main() -> None:
    verify_checkout(LONGMEMEVAL_ROOT)
    sys.path.insert(0, str(PROJECT_ROOT))
    sys.path.insert(0, str(LONGMEMEVAL_ROOT))

    import evaluation.harness as harness
    import evaluation.run_eval as run_eval

    from benchmarks.adapters import engram_longmemeval_v2  # noqa: F401

    original_inject = harness.inject_runtime_memory_params

    def inject_engram_runtime(
        memory_config: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        runtime = original_inject(memory_config, **kwargs)
        if runtime["memory_type"] == "engram_runtime":
            runtime["memory_params"]["workspace_dir"] = str(
                Path(kwargs["workspace_dir"]).resolve()
            )
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
            },
        }

    run_eval.build_memory_config = build_engram_config
    run_eval.main()


if __name__ == "__main__":
    main()
