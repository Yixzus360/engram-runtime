from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import pytest

from engram_runtime.signal_index import SignalIndex
from engram_runtime.state_core import StateCore

DATABASE_URL = os.getenv(
    "ENGRAM_TEST_DATABASE_URL",
    "postgresql://engram:engram@localhost:5439/engram",
)


class KeywordEncoder:
    vocabulary = ("postgres", "python", "crystal", "billing")

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.casefold()
            seed = [float(lowered.count(word)) for word in self.vocabulary]
            seed.extend([0.0] * (768 - len(seed)))
            vectors.append(seed)
        return vectors


class CountingKeywordEncoder(KeywordEncoder):
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return super().encode(texts)


class KeywordRefiner:
    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        words = set(query.casefold().split())
        return [
            float(len(words.intersection(document.casefold().split()))) for document in documents
        ]


@pytest.fixture(scope="module")
def core() -> StateCore:
    instance = StateCore(DATABASE_URL)
    try:
        instance.open()
        instance.migrate()
    except Exception as error:
        pytest.skip(f"State Core is unavailable: {error}")
    yield instance
    instance.close()


def test_hybrid_retrieval_and_refinement(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"signal-{uuid.uuid4().hex[:8]}", "Signal test")
    index = SignalIndex(core, KeywordEncoder(), refiner=KeywordRefiner())
    index.remember(
        workspace["id"],
        experience_form="knowledge_map",
        content="Postgres stores durable runtime state",
        source="test",
    )
    index.remember(
        workspace["id"],
        experience_form="run_journal",
        content="Python renders a crystalline console",
        source="test",
    )

    results = index.search(workspace["id"], "postgres runtime", limit=2)

    assert results[0].content == "Postgres stores durable runtime state"
    assert results[0].rrf_score > 0
    assert results[0].rerank_score == 2.0


def test_fingerprint_normalizes_case_and_spacing() -> None:
    assert SignalIndex.fingerprint(" Durable  Signal ") == SignalIndex.fingerprint("durable signal")


def test_remember_many_embeds_batch_once(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"batch-{uuid.uuid4().hex[:8]}", "Batch test")
    encoder = CountingKeywordEncoder()
    index = SignalIndex(core, encoder)

    rows = index.remember_many(
        workspace["id"],
        [
            {
                "experience_form": "run_journal",
                "content": "Postgres batch one",
                "source": "test",
            },
            {
                "experience_form": "run_journal",
                "content": "Python batch two",
                "source": "test",
            },
        ],
    )

    assert len(rows) == 2
    assert encoder.batch_sizes == [2]


def test_remember_many_uses_supplied_embeddings(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"cached-{uuid.uuid4().hex[:8]}", "Cached test")
    encoder = CountingKeywordEncoder()
    index = SignalIndex(core, encoder)
    embedding = KeywordEncoder().encode(["cached vector"])[0]

    rows = index.remember_many(
        workspace["id"],
        [
            {
                "experience_form": "run_journal",
                "content": "cached vector",
                "source": "test",
                "embedding": embedding,
            }
        ],
    )

    assert len(rows) == 1
    assert encoder.batch_sizes == []
