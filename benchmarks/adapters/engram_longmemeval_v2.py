from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from array import array
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
        self.maximum_chunk_characters = int(memory_params.get("maximum_chunk_characters", 3_500))
        self.batch_size = int(memory_params.get("batch_size", 64))
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        cache_value = str(memory_params.get("embedding_cache_path", "")).strip()
        self.embedding_cache_path = Path(cache_value).resolve() if cache_value else None
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
        self.inserted_trajectory_ids: set[str] = set()
        self.pending_chunks: list[dict[str, Any]] = []
        self.index_seconds = 0.0
        self.embedding_batches = 0
        self.indexed_chunks = 0
        self.embedding_cache_hits = 0
        self.embedding_cache_misses = 0
        self.service = EngramMemoryService.open(RuntimeSettings(workspace_slug=self.workspace_slug))

    @property
    def memory_config(self) -> MemoryConfig:
        return {
            "memory_type": self.memory_type,
            "memory_params": {
                "workspace_slug": self.workspace_slug,
                "workspace_is_resolved": True,
                "top_k": self.top_k,
                "maximum_chunk_characters": self.maximum_chunk_characters,
                "batch_size": self.batch_size,
                "embedding_cache_path": (
                    str(self.embedding_cache_path) if self.embedding_cache_path else None
                ),
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
        chunks = trajectory_chunks(trajectory, maximum_characters=self.maximum_chunk_characters)
        for ordinal, content in enumerate(chunks):
            self.pending_chunks.append(
                {
                    "experience_form": ExperienceForm.RUN_JOURNAL.value,
                    "content": content,
                    "source": "longmemeval-v2",
                    "worker_id": self.service.worker["id"],
                    "confidence": 1.0,
                    "attributes": {
                        "benchmark": "LongMemEval-V2",
                        "trajectory_id": trajectory_id,
                        "chunk_ordinal": ordinal,
                    },
                }
            )
            if len(self.pending_chunks) >= self.batch_size:
                self._flush_pending()
        self.inserted_trajectory_ids.add(trajectory_id)

    def _flush_pending(self) -> None:
        if not self.pending_chunks:
            return
        pending = self.pending_chunks
        self.pending_chunks = []
        started = time.perf_counter()
        try:
            if self.embedding_cache_path is not None:
                vectors = self._cached_embeddings([str(item["content"]) for item in pending])
                pending = [
                    {**item, "embedding": vector}
                    for item, vector in zip(pending, vectors, strict=True)
                ]
            self.service.index.remember_many(
                self.service.workspace["id"],
                pending,
            )
        except Exception:
            self.pending_chunks = pending + self.pending_chunks
            raise
        self.index_seconds += time.perf_counter() - started
        self.embedding_batches += 1
        self.indexed_chunks += len(pending)

    def _cached_embeddings(self, contents: list[str]) -> list[list[float]]:
        if self.embedding_cache_path is None:
            return self.service.encoder.encode(contents)
        self.embedding_cache_path.parent.mkdir(parents=True, exist_ok=True)
        model = str(getattr(self.service.encoder, "model", "unknown"))
        keys = [hashlib.sha256(f"{model}\0{content}".encode()).hexdigest() for content in contents]
        cached: dict[str, list[float]] = {}
        with sqlite3.connect(self.embedding_cache_path, timeout=60) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL
                )
                """
            )
            placeholders = ",".join("?" for _ in keys)
            if placeholders:
                for cache_key, dimensions, blob in connection.execute(
                    f"""
                    SELECT cache_key, dimensions, vector
                      FROM embedding_cache
                     WHERE cache_key IN ({placeholders})
                    """,
                    keys,
                ):
                    values = array("f")
                    values.frombytes(blob)
                    if len(values) == dimensions:
                        cached[cache_key] = values.tolist()

            missing_positions = [
                index for index, cache_key in enumerate(keys) if cache_key not in cached
            ]
            if missing_positions:
                embedded = self.service.encoder.encode(
                    [contents[index] for index in missing_positions]
                )
                if len(embedded) != len(missing_positions):
                    raise RuntimeError("Embedding cache received an invalid vector count")
                for index, vector in zip(missing_positions, embedded, strict=True):
                    cache_key = keys[index]
                    cached[cache_key] = vector
                    blob = array("f", vector).tobytes()
                    connection.execute(
                        """
                        INSERT INTO embedding_cache(cache_key, model, dimensions, vector)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(cache_key) DO UPDATE SET
                            model = excluded.model,
                            dimensions = excluded.dimensions,
                            vector = excluded.vector
                        """,
                        (cache_key, model, len(vector), blob),
                    )
                connection.commit()

        self.embedding_cache_hits += len(contents) - len(missing_positions)
        self.embedding_cache_misses += len(missing_positions)
        return [cached[cache_key] for cache_key in keys]

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        del query_image
        self._flush_pending()
        hits = self.service.ledger.recall(
            self.service.workspace["id"],
            query,
            worker_id=self.service.worker["id"],
            limit=self.top_k,
            refine=False,
        )
        return [{"type": "text", "value": hit.content} for hit in hits if hit.content.strip()]

    def post_query_hook(
        self,
        *,
        query: str,
        query_image: str | None,
        memory_context: list[MemoryContextItem],
    ) -> dict[str, object]:
        del query, query_image, memory_context
        return {
            "engram_index": {
                "seconds": self.index_seconds,
                "embedding_batches": self.embedding_batches,
                "indexed_chunks": self.indexed_chunks,
                "batch_size": self.batch_size,
                "embedding_cache_hits": self.embedding_cache_hits,
                "embedding_cache_misses": self.embedding_cache_misses,
            }
        }

    def _save_backend(self, output_dir: Path) -> None:
        self._flush_pending()
        (output_dir / "engram_state.json").write_text(
            json.dumps(
                {
                    "workspace_slug": self.workspace_slug,
                    "inserted_trajectory_ids": sorted(self.inserted_trajectory_ids),
                    "index_seconds": self.index_seconds,
                    "embedding_batches": self.embedding_batches,
                    "indexed_chunks": self.indexed_chunks,
                    "embedding_cache_hits": self.embedding_cache_hits,
                    "embedding_cache_misses": self.embedding_cache_misses,
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
        self.index_seconds = float(payload.get("index_seconds", 0.0))
        self.embedding_batches = int(payload.get("embedding_batches", 0))
        self.indexed_chunks = int(payload.get("indexed_chunks", 0))
        self.embedding_cache_hits = int(payload.get("embedding_cache_hits", 0))
        self.embedding_cache_misses = int(payload.get("embedding_cache_misses", 0))

    def close(self) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            if hasattr(self, "pending_chunks"):
                self._flush_pending()
            service.close()
            self.service = None

    def __del__(self) -> None:
        self.close()
