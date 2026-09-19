from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import pytest

from engram_runtime.experience_ledger import ExperienceForm, ExperienceLedger
from engram_runtime.signal_index import SignalIndex
from engram_runtime.state_core import StateCore

DATABASE_URL = os.getenv(
    "ENGRAM_TEST_DATABASE_URL",
    "postgresql://engram:engram@localhost:5439/engram",
)


class StableEncoder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            values = [0.0] * 768
            for position, byte in enumerate(text.casefold().encode()):
                values[position % 768] += byte / 255
            vectors.append(values)
        return vectors


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


def test_active_frame_replaces_previous_scope(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"ledger-{uuid.uuid4().hex[:8]}", "Ledger test")
    worker = core.ensure_worker(workspace["id"], "primary", "Primary")
    thread = core.create_thread(workspace["id"], worker["id"], "Frame lifecycle")
    ledger = ExperienceLedger(SignalIndex(core, StableEncoder()))

    ledger.preserve(
        workspace["id"],
        form=ExperienceForm.ACTIVE_FRAME,
        content="The current objective is indexing.",
        source="test",
        worker_id=worker["id"],
        thread_id=thread["id"],
    )
    latest = ledger.preserve(
        workspace["id"],
        form=ExperienceForm.ACTIVE_FRAME,
        content="The current objective is composing attention.",
        source="test",
        worker_id=worker["id"],
        thread_id=thread["id"],
    )

    current = ledger.list_current(
        workspace["id"],
        form=ExperienceForm.ACTIVE_FRAME,
        worker_id=worker["id"],
        thread_id=thread["id"],
    )
    assert [item["id"] for item in current] == [latest["id"]]


def test_expired_experience_is_not_recalled(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"expiry-{uuid.uuid4().hex[:8]}", "Expiry test")
    ledger = ExperienceLedger(SignalIndex(core, StableEncoder()))
    item = ledger.preserve(
        workspace["id"],
        form=ExperienceForm.KNOWLEDGE_MAP,
        content="A temporary billing migration note",
        source="test",
    )
    assert ledger.recall(workspace["id"], "billing migration", refine=False)

    ledger.expire(item["id"])

    assert ledger.recall(workspace["id"], "billing migration", refine=False) == []


def test_preserve_is_idempotent_for_normalized_content(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"dedupe-{uuid.uuid4().hex[:8]}", "Dedupe test")
    ledger = ExperienceLedger(SignalIndex(core, StableEncoder()))
    first = ledger.preserve(
        workspace["id"],
        form=ExperienceForm.KNOWLEDGE_MAP,
        content="Durable fact",
        source="first",
    )
    second = ledger.preserve(
        workspace["id"],
        form=ExperienceForm.KNOWLEDGE_MAP,
        content="  durable   FACT  ",
        source="second",
    )

    assert first["id"] == second["id"]
    assert second["source"] == "second"
