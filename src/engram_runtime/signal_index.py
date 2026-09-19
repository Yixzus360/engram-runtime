from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx

from .state_core import StateCore

EMBEDDING_DIMENSION = 768


class SignalEncoder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class ResultRefiner(Protocol):
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class SignalHit:
    id: UUID
    experience_form: str
    content: str
    source: str
    confidence: float
    attributes: dict[str, Any]
    rrf_score: float
    rerank_score: float | None = None


class OllamaSignalEncoder:
    """Local embedding adapter for Ollama's /api/embed endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        dimension: int = EMBEDDING_DIMENSION,
        timeout_seconds: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": list(texts)},
            )
            response.raise_for_status()
            vectors = response.json()["embeddings"]
        if len(vectors) != len(texts):
            raise ValueError("The encoder returned a different number of vectors than inputs.")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise ValueError(
                    f"Expected {self.dimension} embedding dimensions, received {len(vector)}."
                )
        return vectors


class FastEmbedResultRefiner:
    """Free local cross-encoder loaded only when refinement is requested."""

    def __init__(
        self,
        model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2",
        cache_dir: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir or str(Path.home() / ".cache" / "engram" / "models")
        self._model: Any | None = None

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(
                model_name=self.model_name,
                cache_dir=self.cache_dir,
            )
        return [float(value) for value in self._model.rerank(query, list(documents))]


class SignalIndex:
    """Hybrid lexical/vector index with reciprocal-rank fusion and local refinement."""

    def __init__(
        self,
        core: StateCore,
        encoder: SignalEncoder,
        *,
        refiner: ResultRefiner | None = None,
        rrf_constant: int = 60,
    ) -> None:
        self.core = core
        self.encoder = encoder
        self.refiner = refiner
        self.rrf_constant = rrf_constant

    @staticmethod
    def fingerprint(content: str) -> str:
        normalized = " ".join(content.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def remember(
        self,
        workspace_id: UUID,
        *,
        experience_form: str,
        content: str,
        source: str,
        worker_id: UUID | None = None,
        thread_id: UUID | None = None,
        confidence: float = 1.0,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        vector = self.encoder.encode([content])[0]
        digest = self.fingerprint(content)
        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO engram_experience (
                    workspace_id, worker_id, thread_id, experience_form, content,
                    fingerprint, source, confidence, attributes, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, experience_form, fingerprint)
                DO UPDATE SET
                    worker_id = EXCLUDED.worker_id,
                    thread_id = EXCLUDED.thread_id,
                    source = EXCLUDED.source,
                    confidence = EXCLUDED.confidence,
                    attributes = EXCLUDED.attributes,
                    embedding = EXCLUDED.embedding,
                    superseded_by = NULL,
                    expires_at = NULL,
                    updated_at = now()
                RETURNING *
                """,
                (
                    workspace_id,
                    worker_id,
                    thread_id,
                    experience_form,
                    content,
                    digest,
                    source,
                    confidence,
                    json.dumps(attributes or {}),
                    vector,
                ),
            )
            row = cursor.fetchone()
            connection.commit()
            return row

    def search(
        self,
        workspace_id: UUID,
        query: str,
        *,
        limit: int = 6,
        candidate_limit: int = 24,
        worker_id: UUID | None = None,
        thread_id: UUID | None = None,
        forms: Sequence[str] | None = None,
        refine: bool = True,
    ) -> list[SignalHit]:
        if not query.strip() or limit < 1:
            return []
        query_vector = self.encoder.encode([query])[0]
        filters, params = self._scope_filter(workspace_id, worker_id, thread_id, forms)
        where_clause = " AND ".join(filters)

        with self.core.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, experience_form, content, source, confidence, attributes,
                       ts_rank_cd(search_document, plainto_tsquery('simple', %s)) AS score
                  FROM engram_experience
                 WHERE {where_clause}
                   AND search_document @@ plainto_tsquery('simple', %s)
                 ORDER BY score DESC, updated_at DESC
                 LIMIT %s
                """,
                (query, *params, query, candidate_limit),
            )
            lexical = list(cursor.fetchall())
            cursor.execute(
                f"""
                SELECT id, experience_form, content, source, confidence, attributes,
                       1 - (embedding <=> %s::vector) AS score
                  FROM engram_experience
                 WHERE {where_clause} AND embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector, updated_at DESC
                 LIMIT %s
                """,
                (query_vector, *params, query_vector, candidate_limit),
            )
            semantic = list(cursor.fetchall())

        fused: dict[UUID, dict[str, Any]] = {}
        for ranking in (lexical, semantic):
            for rank, row in enumerate(ranking, start=1):
                item = fused.setdefault(row["id"], {**row, "rrf_score": 0.0})
                item["rrf_score"] += 1.0 / (self.rrf_constant + rank)

        candidates = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
        rerank_scores: dict[UUID, float] = {}
        if refine and self.refiner and candidates:
            scores = self.refiner.score(query, [item["content"] for item in candidates])
            if len(scores) != len(candidates):
                raise ValueError("The result refiner returned an invalid score count.")
            rerank_scores = {
                item["id"]: score
                for item, score in zip(candidates, scores, strict=True)
            }
            candidates.sort(
                key=lambda item: (rerank_scores[item["id"]], item["rrf_score"]), reverse=True
            )

        return [
            SignalHit(
                id=item["id"],
                experience_form=item["experience_form"],
                content=item["content"],
                source=item["source"],
                confidence=float(item["confidence"]),
                attributes=item["attributes"],
                rrf_score=item["rrf_score"],
                rerank_score=rerank_scores.get(item["id"]),
            )
            for item in candidates[:limit]
        ]

    @staticmethod
    def _scope_filter(
        workspace_id: UUID,
        worker_id: UUID | None,
        thread_id: UUID | None,
        forms: Sequence[str] | None,
    ) -> tuple[list[str], list[Any]]:
        filters = [
            "workspace_id = %s",
            "superseded_by IS NULL",
            "(expires_at IS NULL OR expires_at > now())",
        ]
        params: list[Any] = [workspace_id]
        if worker_id:
            filters.append("(worker_id IS NULL OR worker_id = %s)")
            params.append(worker_id)
        if thread_id:
            filters.append("(thread_id IS NULL OR thread_id = %s)")
            params.append(thread_id)
        if forms:
            filters.append("experience_form = ANY(%s)")
            params.append(list(forms))
        return filters, params


def logistic_score(value: float) -> float:
    """Map an arbitrary cross-encoder score to a stable 0..1 display value."""
    return 1.0 / (1.0 + math.exp(-value))
