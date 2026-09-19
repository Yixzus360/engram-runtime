from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

from engram_runtime.longmemeval import (
    LONGMEMEVAL_DATASET_ID,
    LONGMEMEVAL_DATASET_REVISION,
    text_dataset_allow_patterns,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the pinned text-first LongMemEval-V2 pilot subset"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-medium", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=LONGMEMEVAL_DATASET_ID,
        repo_type="dataset",
        revision=LONGMEMEVAL_DATASET_REVISION,
        local_dir=output_dir,
        allow_patterns=text_dataset_allow_patterns(args.include_medium),
    )
    print(
        json.dumps(
            {
                "dataset": LONGMEMEVAL_DATASET_ID,
                "revision": LONGMEMEVAL_DATASET_REVISION,
                "output_dir": str(output_dir),
                "mode": "text-first",
                "trajectory_screenshot_archives_downloaded": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
