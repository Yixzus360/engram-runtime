from __future__ import annotations

import os
import uuid

import pytest

from engram_runtime.state_core import StateCore

DATABASE_URL = os.getenv(
    "ENGRAM_TEST_DATABASE_URL",
    "postgresql://engram:engram@localhost:5439/engram",
)


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


def test_persistence_and_run_record(core: StateCore) -> None:
    suffix = uuid.uuid4().hex[:8]
    workspace = core.ensure_workspace(f"test-{suffix}", "State Core test")
    worker = core.ensure_worker(workspace["id"], "primary", "Primary worker")
    thread = core.create_thread(workspace["id"], worker["id"], "Persistence test")
    entry = core.append_entry(thread["id"], "operator", "Persist this request")
    run = core.start_run(thread["id"], entry["body"], "local")
    core.emit_record(run["id"], "run_started", {"stage": "state_core"})
    finished = core.finish_run(
        run["id"], status="complete", outcome="Persistence verified", usage={"calls": 0}
    )

    assert finished["status"] == "complete"
    assert core.list_records(run["id"])[0]["payload"]["stage"] == "state_core"


def test_output_anchoring_deduplicates(core: StateCore) -> None:
    suffix = uuid.uuid4().hex[:8]
    workspace = core.ensure_workspace(f"output-{suffix}", "Output test")
    payload = "crystalline-output-" * 100

    first = core.anchor_output(workspace["id"], payload, preview_bytes=120)
    second = core.anchor_output(workspace["id"], payload, preview_bytes=120)

    assert first.id == second.id
    assert first.byte_count == len(payload.encode())
    assert "stored output" in first.preview
    assert core.fetch_output(workspace["id"], first.id) == payload.encode()
