from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Sequence

import pytest
from mcp.client import Client

from engram_runtime.mcp_server import EngramMemoryService, build_server
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


def new_service(core: StateCore) -> EngramMemoryService:
    return EngramMemoryService(
        core,
        StableEncoder(),
        workspace_slug=f"mcp-test-{uuid.uuid4().hex[:8]}",
    )


def test_memory_boundary_is_scoped_idempotent_and_bounded(core: StateCore) -> None:
    service = new_service(core)
    first = service.preserve(
        kind="decision",
        content="Keep the MCP workspace isolated from normal console conversations.",
        task="Connect Codex to Engram",
        evidence="The project config sets a dedicated workspace slug.",
        success=True,
    )
    second = service.preserve(
        kind="decision",
        content="  keep the MCP workspace ISOLATED from normal console conversations. ",
        task="Connect Codex to Engram",
        evidence="Repeated storage verifies fingerprint deduplication.",
        success=True,
    )

    recalled = service.recall("How is the Codex MCP workspace isolated?", limit=10)

    assert first["id"] == second["id"]
    assert recalled["workspace"] == service.workspace_slug
    assert recalled["signal_count"] == 1
    assert recalled["limit_used"] == 3
    assert "workspace isolated" in recalled["signals"][0]["content"]
    assert recalled["estimated_context_tokens"] < 200
    rendered = service.render_recall(recalled)
    assert rendered.count("workspace isolated") == 1


def test_memory_boundary_rejects_secrets_and_inconsistent_evidence(core: StateCore) -> None:
    service = new_service(core)
    common = {
        "task": "Configure provider",
        "evidence": "Validated locally",
        "confidence": 1.0,
    }
    with pytest.raises(ValueError, match="credential"):
        service.preserve(
            kind="fact",
            content="api_key=super-secret-value-that-must-not-be-stored",
            success=True,
            **common,
        )
    with pytest.raises(ValueError, match="credential"):
        fake_openai_key = "sk-" + "proj-" + ("x" * 32)
        service.preserve(
            kind="fact",
            content=f"Use {fake_openai_key} for this test.",
            success=True,
            **common,
        )
    with pytest.raises(ValueError, match="success=false"):
        service.preserve(
            kind="failure",
            content="The database was unavailable.",
            success=True,
            **common,
        )


def test_mcp_contract_lists_and_calls_tools(core: StateCore) -> None:
    async def scenario() -> None:
        service = new_service(core)
        server = build_server(service)
        async with Client(server) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} == {
                "runtime_status",
                "recall_signals",
                "preserve_signal",
            }
            assert next(
                tool for tool in listed.tools if tool.name == "runtime_status"
            ).annotations.read_only_hint

            status = await client.call_tool("runtime_status")
            assert not status.is_error
            assert status.structured_content["ready"] is True
            assert status.structured_content["workspace"] == service.workspace_slug

            recall = await client.call_tool(
                "recall_signals", {"task": "Check isolated memory", "limit": 1}
            )
            assert not recall.is_error
            assert recall.structured_content is None
            assert recall.content[0].text.startswith(f"workspace={service.workspace_slug}")

    asyncio.run(scenario())
