from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from jsonschema import ValidationError

from engram_runtime.builtin_actions import read_workspace_text, write_workspace_text
from engram_runtime.capability_forge import (
    ActionContext,
    CapabilityForge,
    action_contract,
)
from engram_runtime.state_core import StateCore

DATABASE_URL = os.getenv(
    "ENGRAM_TEST_DATABASE_URL",
    "postgresql://engram:engram@localhost:5439/engram",
)


class StableEncoder:
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * 768
            for index, value in enumerate(text.casefold().encode()):
                vector[index % 768] += value / 255
            vectors.append(vector)
        return vectors


@action_contract(
    name="add_numbers",
    description="Add two numbers and return their sum.",
    input_contract={
        "type": "object",
        "properties": {"left": {"type": "number"}, "right": {"type": "number"}},
        "required": ["left", "right"],
        "additionalProperties": False,
    },
    output_contract={
        "type": "object",
        "properties": {"sum": {"type": "number"}},
        "required": ["sum"],
        "additionalProperties": False,
    },
)
def add_numbers(arguments: dict[str, Any], _context: ActionContext) -> dict[str, float]:
    return {"sum": arguments["left"] + arguments["right"]}


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


def test_action_contract_registration_selection_and_invocation(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"forge-{uuid.uuid4().hex[:8]}", "Forge test")
    forge = CapabilityForge(core, StableEncoder())
    stored = forge.register(workspace["id"], add_numbers)

    selected = forge.select_actions(workspace["id"], "add two values")
    receipt = forge.invoke(workspace["id"], "add_numbers", {"left": 2, "right": 5})

    assert stored["name"] == "add_numbers"
    assert selected[0]["name"] == "add_numbers"
    assert receipt.output == {"sum": 7}
    with pytest.raises(ValidationError):
        forge.invoke(workspace["id"], "add_numbers", {"left": 2})


def test_procedure_requires_distinct_successful_runs(core: StateCore) -> None:
    workspace = core.ensure_workspace(f"procedure-{uuid.uuid4().hex[:8]}", "Procedure test")
    worker = core.ensure_worker(workspace["id"], "primary", "Primary")
    thread = core.create_thread(workspace["id"], worker["id"], "Repeatable task")
    forge = CapabilityForge(core, StableEncoder(), verification_threshold=2)

    first_run = core.start_run(thread["id"], "Add values", "test")
    core.emit_record(
        first_run["id"],
        "action_dispatch",
        {"action": "add_numbers", "arguments": {"left": 2, "right": 5}},
    )
    core.finish_run(first_run["id"], status="complete", outcome="7")
    candidate = forge.distill_candidate(
        workspace["id"],
        first_run["id"],
        name="add-known-values",
        description="Adds the requested values with the registered action.",
        trigger_text="add these values",
    )
    assert candidate["status"] == "candidate"
    assert forge.find_verified_procedures(workspace["id"], "add values") == []

    second_run = core.start_run(thread["id"], "Add values again", "test")
    core.finish_run(second_run["id"], status="complete", outcome="7")
    verified = forge.add_verification(candidate["id"], second_run["id"], successful=True)

    assert verified["status"] == "verified"
    assert forge.find_verified_procedures(workspace["id"], "add values")[0]["id"] == candidate["id"]


def test_workspace_actions_reject_path_escape(core: StateCore, tmp_path: Any) -> None:
    workspace = core.ensure_workspace(f"files-{uuid.uuid4().hex[:8]}", "File action test")
    forge = CapabilityForge(core, StableEncoder())
    forge.register(workspace["id"], read_workspace_text)
    forge.register(workspace["id"], write_workspace_text)
    context = ActionContext(workspace_id=workspace["id"], root_path=tmp_path)

    receipt = forge.invoke(
        workspace["id"],
        "write_workspace_text",
        {"path": "notes/result.txt", "content": "verified"},
        context=context,
    )
    assert receipt.output["characters"] == 8
    assert (
        forge.invoke(
            workspace["id"],
            "read_workspace_text",
            {"path": "notes/result.txt"},
            context=context,
        ).output["content"]
        == "verified"
    )
    with pytest.raises(ValueError, match="escapes"):
        forge.invoke(
            workspace["id"],
            "read_workspace_text",
            {"path": "../outside.txt"},
            context=context,
        )
