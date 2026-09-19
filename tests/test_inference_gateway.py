from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from engram_runtime.inference_gateway import (
    GatewayOutput,
    GatewayTool,
    LiteLLMProvider,
    standard_router,
)


class Message(SimpleNamespace):
    def model_dump(self, *, exclude_none: bool) -> dict[str, Any]:
        del exclude_none
        payload: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return payload


def test_litellm_bridge_preserves_tool_conversation() -> None:
    calls: list[dict[str, Any]] = []
    responses = [
        SimpleNamespace(
            id="one",
            choices=[
                SimpleNamespace(
                    message=Message(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="calculate", arguments='{"expression":"2+2"}'
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3),
        ),
        SimpleNamespace(
            id="two",
            choices=[SimpleNamespace(message=Message(content="4", tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=1),
        ),
    ]

    def completion(**options: Any) -> Any:
        calls.append(options)
        return responses.pop(0)

    provider = LiteLLMProvider("anthropic/example", completion_fn=completion)
    tool = GatewayTool(
        name="calculate",
        description="Calculate.",
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    )
    first = provider.start(instructions="Use tools.", prompt="2+2", tools=[tool])
    second = provider.continue_with_outputs(
        first,
        [GatewayOutput("call-1", {"value": 4})],
        instructions="Use tools.",
        tools=[tool],
    )

    assert first.calls[0].name == "calculate"
    assert second.text == "4"
    assert calls[1]["messages"][-1]["tool_call_id"] == "call-1"


def test_standard_router_exposes_four_cost_profiles() -> None:
    router = standard_router(local_model="local-model")
    assert [profile.name for profile in router.list_profiles()] == [
        "local",
        "economy",
        "balanced",
        "frontier",
    ]
    assert router.resolve("frontier").model == "gpt-6-astra"
