from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GatewayTool:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class GatewayCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class GatewayOutput:
    call_id: str
    content: Any


@dataclass(frozen=True)
class GatewayTurn:
    text: str
    calls: tuple[GatewayCall, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    state: Any = None
    response_id: str | None = None


class InferenceProvider(Protocol):
    provider_name: str
    model: str

    def start(
        self,
        *,
        instructions: str,
        prompt: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn: ...

    def continue_with_outputs(
        self,
        previous: GatewayTurn,
        outputs: Sequence[GatewayOutput],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn: ...


class OllamaProvider:
    provider_name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 180,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def start(
        self,
        *,
        instructions: str,
        prompt: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ]
        return self._respond(messages, tools)

    def continue_with_outputs(
        self,
        previous: GatewayTurn,
        outputs: Sequence[GatewayOutput],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        del instructions
        messages = list(previous.state)
        calls_by_id = {call.call_id: call for call in previous.calls}
        for output in outputs:
            call = calls_by_id[output.call_id]
            messages.append(
                {
                    "role": "tool",
                    "tool_name": call.name,
                    "content": json.dumps(output.content, default=str),
                }
            )
        return self._respond(messages, tools)

    def _respond(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        message = data["message"]
        state = [*messages, message]
        calls = tuple(
            self._ollama_call(item, index)
            for index, item in enumerate(message.get("tool_calls", []))
        )
        return GatewayTurn(
            text=message.get("content", ""),
            calls=calls,
            usage={
                "input_tokens": int(data.get("prompt_eval_count", 0)),
                "output_tokens": int(data.get("eval_count", 0)),
            },
            state=state,
        )

    @staticmethod
    def _ollama_call(item: dict[str, Any], index: int) -> GatewayCall:
        function = item["function"]
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        call_id = item.get("id") or f"ollama-{index}-{function['name']}"
        return GatewayCall(call_id=call_id, name=function["name"], arguments=arguments)


class OpenAIResponsesProvider:
    provider_name = "openai"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
        max_output_tokens: int = 1200,
        timeout_seconds: float = 180,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self._client: Any | None = None

    def start(
        self,
        *,
        instructions: str,
        prompt: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        return self._respond(
            [{"role": "user", "content": prompt}],
            instructions=instructions,
            tools=tools,
        )

    def continue_with_outputs(
        self,
        previous: GatewayTurn,
        outputs: Sequence[GatewayOutput],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        input_items = list(previous.state)
        input_items.extend(
            {
                "type": "function_call_output",
                "call_id": output.call_id,
                "output": json.dumps(output.content, default=str),
            }
            for output in outputs
        )
        return self._respond(input_items, instructions=instructions, tools=tools)

    def _respond(
        self,
        input_items: list[Any],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": [self._openai_tool(tool) for tool in tools],
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "max_output_tokens": self.max_output_tokens,
        }
        if self.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self._get_client().responses.create(**kwargs)
        calls = tuple(
            GatewayCall(
                call_id=item.call_id,
                name=item.name,
                arguments=json.loads(item.arguments),
            )
            for item in response.output
            if item.type == "function_call"
        )
        usage = response.usage
        state = [*input_items, *response.output]
        return GatewayTurn(
            text=response.output_text,
            calls=calls,
            usage={
                "input_tokens": int(usage.input_tokens if usage else 0),
                "output_tokens": int(usage.output_tokens if usage else 0),
            },
            state=state,
            response_id=response.id,
        )

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            options: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": self.timeout_seconds,
            }
            if self.base_url:
                options["base_url"] = self.base_url
            self._client = OpenAI(**options)
        return self._client

    @staticmethod
    def _openai_tool(tool: GatewayTool) -> dict[str, Any]:
        properties = set(tool.parameters.get("properties", {}))
        required = set(tool.parameters.get("required", []))
        strict = tool.parameters.get("additionalProperties") is False and properties == required
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "strict": strict,
        }


class LiteLLMProvider:
    """Optional open-source bridge for Claude, Gemini, hosted Llama, and others."""

    provider_name = "litellm"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        max_tokens: int = 1200,
        timeout_seconds: float = 180,
        completion_fn: Any | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self._completion_fn = completion_fn

    def start(
        self,
        *,
        instructions: str,
        prompt: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ]
        return self._respond(messages, tools)

    def continue_with_outputs(
        self,
        previous: GatewayTurn,
        outputs: Sequence[GatewayOutput],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        del instructions
        messages = list(previous.state)
        calls_by_id = {call.call_id: call for call in previous.calls}
        for output in outputs:
            call = calls_by_id[output.call_id]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": output.call_id,
                    "name": call.name,
                    "content": json.dumps(output.content, default=str),
                }
            )
        return self._respond(messages, tools)

    def _respond(
        self,
        messages: list[dict[str, Any]],
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        options: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout_seconds,
        }
        if tools:
            options["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
        if self.api_key:
            options["api_key"] = self.api_key
        if self.api_base:
            options["api_base"] = self.api_base
        response = self._completion()(**options)
        message = response.choices[0].message
        serialized = (
            message.model_dump(exclude_none=True)
            if hasattr(message, "model_dump")
            else dict(message)
        )
        calls = tuple(
            GatewayCall(
                call_id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments),
            )
            for call in (message.tool_calls or [])
        )
        usage = response.usage
        return GatewayTurn(
            text=message.content or "",
            calls=calls,
            usage={
                "input_tokens": int(usage.prompt_tokens if usage else 0),
                "output_tokens": int(usage.completion_tokens if usage else 0),
            },
            state=[*messages, serialized],
            response_id=getattr(response, "id", None),
        )

    def _completion(self) -> Any:
        if self._completion_fn is None:
            try:
                from litellm import completion
            except ImportError as error:
                raise RuntimeError(
                    "Install the universal provider bridge with: uv sync --extra universal"
                ) from error
            self._completion_fn = completion
        return self._completion_fn


class ScriptedProvider:
    """Deterministic provider for offline tests and reproducible demonstrations."""

    provider_name = "scripted"
    model = "scripted"

    def __init__(self, turns: Sequence[GatewayTurn]) -> None:
        self._turns = list(turns)

    def start(
        self,
        *,
        instructions: str,
        prompt: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        del instructions, prompt, tools
        return self._next()

    def continue_with_outputs(
        self,
        previous: GatewayTurn,
        outputs: Sequence[GatewayOutput],
        *,
        instructions: str,
        tools: Sequence[GatewayTool],
    ) -> GatewayTurn:
        del previous, outputs, instructions, tools
        return self._next()

    def _next(self) -> GatewayTurn:
        if not self._turns:
            raise RuntimeError("scripted provider has no remaining turns")
        return self._turns.pop(0)


@dataclass(frozen=True)
class InferenceProfile:
    name: str
    provider: str
    model: str
    reasoning_effort: str | None
    max_output_tokens: int


class InferenceRouter:
    def __init__(self, profiles: Sequence[InferenceProfile]) -> None:
        self._profiles = {profile.name: profile for profile in profiles}

    def resolve(self, profile_name: str) -> InferenceProfile:
        try:
            return self._profiles[profile_name]
        except KeyError as error:
            available = ", ".join(sorted(self._profiles))
            message = f"Unknown inference profile '{profile_name}'. Available: {available}"
            raise LookupError(message) from error

    def list_profiles(self) -> list[InferenceProfile]:
        return list(self._profiles.values())


def standard_router(
    *,
    local_model: str,
    economy_model: str = "gpt-5.6-luna",
    balanced_model: str = "gpt-5.6-terra",
    frontier_model: str = "gpt-6-astra",
) -> InferenceRouter:
    return InferenceRouter(
        [
            InferenceProfile("local", "ollama", local_model, None, 1200),
            InferenceProfile("economy", "openai", economy_model, "low", 1200),
            InferenceProfile("balanced", "openai", balanced_model, "medium", 1800),
            InferenceProfile("frontier", "openai", frontier_model, "high", 2400),
        ]
    )
