from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from memory_modules.memory import Memory, MemoryConfig, MemoryContextItem, register_memory

from engram_runtime.config import RuntimeSettings
from engram_runtime.experience_ledger import ExperienceForm
from engram_runtime.longmemeval import trajectory_chunks
from engram_runtime.mcp_server import EngramMemoryService


@register_memory
class EngramLongMemEvalMemory(Memory):
    """LongMemEval-V2 adapter backed by Engram's local PostgreSQL/pgvector state."""

    memory_type = "engram_runtime"

    def __init__(self, memory_params: dict[str, object]) -> None:
        super().__init__(memory_params)
        self.top_k = int(memory_params.get("top_k", 6))
        self.maximum_chunk_characters = int(
            memory_params.get("maximum_chunk_characters", 3_500)
        )
        base_slug = str(memory_params.get("workspace_slug", "longmemeval-v2"))
        workspace_dir = str(memory_params.get("workspace_dir", "")).strip()
        if memory_params.get("workspace_is_resolved") is True:
            self.workspace_slug = base_slug
        else:
            suffix = (
                hashlib.sha256(workspace_dir.encode("utf-8")).hexdigest()[:12]
                if workspace_dir
                else "shared"
            )
            self.workspace_slug = f"{base_slug}-{suffix}"
        self.service = EngramMemoryService.open(
            RuntimeSettings(workspace_slug=self.workspace_slug)
        )
        self.inserted_trajectory_ids: set[str] = set()

    @property
    def memory_config(self) -> MemoryConfig:
        return {
            "memory_type": self.memory_type,
            "memory_params": {
                "workspace_slug": self.workspace_slug,
                "workspace_is_resolved": True,
                "top_k": self.top_k,
                "maximum_chunk_characters": self.maximum_chunk_characters,
            },
        }

    @classmethod
    def reconcile_loaded_memory_config(
        cls,
        saved_config: MemoryConfig,
        requested_config: MemoryConfig | None,
    ) -> MemoryConfig:
        if saved_config["memory_type"] != cls.memory_type:
            raise RuntimeError("Saved memory is not an Engram Runtime memory")
        if requested_config is not None and requested_config["memory_type"] != cls.memory_type:
            raise RuntimeError("Requested memory is not an Engram Runtime memory")
        return saved_config

    def insert(self, trajectory: dict[str, object]) -> None:
        trajectory_id = str(trajectory.get("id") or "").strip()
        if not trajectory_id:
            raise RuntimeError("trajectory id must be a non-empty string")
        if trajectory_id in self.inserted_trajectory_ids:
            raise RuntimeError(f"Duplicate trajectory insert attempted: {trajectory_id}")
        chunks = trajectory_chunks(
            trajectory, maximum_characters=self.maximum_chunk_characters
        )
        for ordinal, content in enumerate(chunks):
            self.service.ledger.preserve(
                self.service.workspace["id"],
                form=ExperienceForm.RUN_JOURNAL,
                content=content,
                source="longmemeval-v2",
                worker_id=self.service.worker["id"],
                confidence=1.0,
                attributes={
                    "benchmark": "LongMemEval-V2",
                    "trajectory_id": trajectory_id,
                    "chunk_ordinal": ordinal,
                },
                replace_scope=False,
            )
        self.inserted_trajectory_ids.add(trajectory_id)

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        del query_image
        hits = self.service.ledger.recall(
            self.service.workspace["id"],
            query,
            worker_id=self.service.worker["id"],
            limit=self.top_k,
            refine=False,
        )
        return [
            {"type": "text", "value": hit.content}
            for hit in hits
            if hit.content.strip()
        ]

    def _save_backend(self, output_dir: Path) -> None:
        (output_dir / "engram_state.json").write_text(
            json.dumps(
                {
                    "workspace_slug": self.workspace_slug,
                    "inserted_trajectory_ids": sorted(self.inserted_trajectory_ids),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _load_backend(self, input_dir: Path) -> None:
        path = input_dir / "engram_state.json"
        if not path.exists():
            return
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self.inserted_trajectory_ids = set(payload.get("inserted_trajectory_ids", []))

    def close(self) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            service.close()
            self.service = None

    def __del__(self) -> None:
        self.close()
