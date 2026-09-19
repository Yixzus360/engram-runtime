from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Any

import pytest

from engram_runtime.action_cycle import ActionCycle
from engram_runtime.capability_forge import (
    ActionContext,
    ActionUnit,
    CapabilityForge,
    RiskLevel,
)
from engram_runtime.inference_gateway import (
    GatewayCall,
    GatewayTurn,
    ScriptedProvider,
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


def add(arguments: dict[str, Any], _context: ActionContext) -> dict[str, float]:
    return {"sum": arguments["left"] + arguments["right"]}


ADD_ACTION = ActionUnit(
    name="add",
    description="Add two numbers.",
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
    handler=add,
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


def cycle_fixture(core: StateCore) -> tuple[dict[str, Any], dict[str, Any], CapabilityForge]:
    workspace = core.ensure_workspace(f"cycle-{uuid.uuid4().hex[:8]}", "Cycle test")
    worker = core.ensure_worker(workspace["id"], "primary", "Primary")
    thread = core.create_thread(workspace["id"], worker["id"], "Action cycle")
    forge = CapabilityForge(core, StableEncoder())
    forge.register(workspace["id"], ADD_ACTION)
    return workspace, thread, forge


def test_action_cycle_executes_and_records(core: StateCore) -> None:
    workspace, thread, forge = cycle_fixture(core)
    provider = ScriptedProvider(
        [
            GatewayTurn(
                text="",
                calls=(GatewayCall("call-1", "add", {"left": 2, "right": 5}),),
                usage={"input_tokens": 10, "output_tokens": 3},
            ),
            GatewayTurn(
                text="The result is 7.",
                usage={"input_tokens": 12, "output_tokens": 4},
            ),
        ]
    )

    result = ActionCycle(core, forge).run(
        workspace["id"],
        thread["id"],
        "Add 2 and 5",
        provider=provider,
        instructions="Use actions when needed.",
    )
    records = core.list_records(result.run_id)

    assert result.status == "complete"
    assert result.dispatches == 1
    assert result.usage == {"input_tokens": 22, "output_tokens": 7, "inference_calls": 2}
    assert any(record["record_kind"] == "action_dispatch" for record in records)


def test_write_action_requires_operator_gate(core: StateCore) -> None:
    workspace, thread, forge = cycle_fixture(core)
    writes: list[str] = []

    def write(arguments: dict[str, Any], _context: ActionContext) -> dict[str, bool]:
        writes.append(arguments["value"])
        return {"written": True}

    forge.register(
        workspace["id"],
        ActionUnit(
            name="write",
            description="Write a value.",
            input_contract={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            output_contract={
                "type": "object",
                "properties": {"written": {"type": "boolean"}},
                "required": ["written"],
                "additionalProperties": False,
            },
            handler=write,
            risk_level=RiskLevel.WRITE,
        ),
    )
    provider = ScriptedProvider(
        [
            GatewayTurn(calls=(GatewayCall("write-1", "write", {"value": "x"}),), text=""),
            GatewayTurn(text="The write was not authorized."),
        ]
    )

    result = ActionCycle(core, forge).run(
        workspace["id"],
        thread["id"],
        "Write x",
        provider=provider,
        instructions="Respect authorization.",
    )

    assert result.status == "complete"
    assert writes == []
    assert any(
        record["record_kind"] == "operator_gate_denied"
        for record in core.list_records(result.run_id)
    )


def test_repetition_guard_stops_loop(core: StateCore) -> None:
    workspace, thread, forge = cycle_fixture(core)
    repeated = GatewayTurn(
        text="",
        calls=(GatewayCall("repeat", "add", {"left": 1, "right": 1}),),
    )
    provider = ScriptedProvider([repeated, repeated, repeated])

    result = ActionCycle(core, forge).run(
        workspace["id"],
        thread["id"],
        "Repeat forever",
        provider=provider,
        instructions="Test guard.",
    )

    assert result.status == "stopped"
    assert result.dispatches == 2
    assert "repeated action blocked" in result.answer
