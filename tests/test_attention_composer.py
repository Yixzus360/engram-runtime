from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest

from engram_runtime.action_cycle import ActionCycle
from engram_runtime.attention_composer import AttentionComposer
from engram_runtime.capability_forge import ActionContext, ActionUnit, CapabilityForge
from engram_runtime.experience_ledger import ExperienceForm, ExperienceLedger
from engram_runtime.inference_gateway import GatewayCall, GatewayTurn, ScriptedProvider
from engram_runtime.pattern_learner import PatternLearner
from engram_runtime.signal_index import SignalIndex
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


def echo(arguments: dict[str, Any], _context: ActionContext) -> dict[str, Any]:
    return {"value": arguments["value"]}


ECHO_ACTION = ActionUnit(
    name="echo_value",
    description="Return the provided value.",
    input_contract={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    output_contract={
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
    handler=echo,
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


def new_runtime(core: StateCore) -> tuple[dict[str, Any], dict[str, Any], CapabilityForge]:
    workspace = core.ensure_workspace(f"attention-{uuid.uuid4().hex[:8]}", "Attention test")
    worker = core.ensure_worker(workspace["id"], "primary", "Primary")
    thread = core.create_thread(workspace["id"], worker["id"], "Attention")
    forge = CapabilityForge(core, StableEncoder())
    forge.register(workspace["id"], ECHO_ACTION)
    return workspace, thread, forge


def complete_action_run(
    core: StateCore,
    thread_id: UUID,
    request: str,
    value: str,
) -> dict[str, Any]:
    run = core.start_run(thread_id, request, "scripted")
    core.emit_record(
        run["id"],
        "action_dispatch",
        {"action": "echo_value", "arguments": {"value": value}},
    )
    return core.finish_run(run["id"], status="complete", outcome=value)


def test_candidate_compresses_second_focus_packet(core: StateCore) -> None:
    workspace, thread, forge = new_runtime(core)
    ledger = ExperienceLedger(SignalIndex(core, StableEncoder()))
    request = "repeat the customer normalization workflow"
    for index in range(8):
        core.append_entry(
            thread["id"],
            "operator" if index % 2 == 0 else "worker",
            f"Long prior exchange {index}: " + "context " * 25,
        )
    for index in range(6):
        ledger.preserve(
            workspace["id"],
            form=ExperienceForm.RUN_JOURNAL,
            content=f"Historical signal {index}: " + "evidence " * 22,
            source="test",
        )
    composer = AttentionComposer(core, ledger, forge)
    before = composer.compose(
        workspace["id"],
        thread["id"],
        request,
        base_instructions="Complete the request accurately.",
    )

    first_run = complete_action_run(core, thread["id"], request, "normalized")
    receipt = PatternLearner(forge).observe_success(
        workspace["id"], first_run["id"], request
    )
    after = composer.compose(
        workspace["id"],
        thread["id"],
        request,
        base_instructions="Complete the request accurately.",
    )

    assert receipt.created is True
    assert after.reused_procedure is True
    assert after.estimated_tokens < before.estimated_tokens
    assert after.estimated_tokens_avoided > 0


def test_second_success_promotes_learned_procedure(core: StateCore) -> None:
    workspace, thread, forge = new_runtime(core)
    learner = PatternLearner(forge)
    request = "echo the validated account marker"
    first = complete_action_run(core, thread["id"], request, "valid")
    second = complete_action_run(core, thread["id"], request, "valid")

    created = learner.observe_success(workspace["id"], first["id"], request)
    promoted = learner.observe_success(workspace["id"], second["id"], request)

    assert created.status == "candidate"
    assert promoted.status == "verified"
    assert promoted.created is False


def test_large_action_output_is_anchored(core: StateCore) -> None:
    workspace, thread, forge = new_runtime(core)
    huge_action = ActionUnit(
        name="huge_output",
        description="Return a large local payload.",
        input_contract={"type": "object", "properties": {}, "additionalProperties": False},
        output_contract={
            "type": "object",
            "properties": {"data": {"type": "string"}},
            "required": ["data"],
            "additionalProperties": False,
        },
        handler=lambda _arguments, _context: {"data": "x" * 4_000},
    )
    forge.register(workspace["id"], huge_action)
    provider = ScriptedProvider(
        [
            GatewayTurn(text="", calls=(GatewayCall("huge-1", "huge_output", {}),)),
            GatewayTurn(text="The output was stored."),
        ]
    )
    result = ActionCycle(core, forge, output_inline_bytes=120).run(
        workspace["id"],
        thread["id"],
        "Produce the large output",
        provider=provider,
        instructions="Use the action.",
    )
    action_result = next(
        record
        for record in core.list_records(result.run_id)
        if record["record_kind"] == "action_result"
    )

    compact = action_result["payload"]["output"]
    assert result.status == "complete"
    assert compact["byte_count"] > 4_000
    assert len(compact["preview"]) < 250
    assert core.fetch_output(workspace["id"], UUID(compact["stored_output_id"])) is not None
