from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .capability_forge import ActionContext, CapabilityForge, RiskLevel
from .inference_gateway import (
    GatewayOutput,
    GatewayTool,
    GatewayTurn,
    InferenceProvider,
)
from .pattern_learner import PatternLearner
from .state_core import StateCore

OperatorGate = Callable[[RiskLevel, str, dict[str, Any]], bool]


@dataclass(frozen=True)
class CycleLimits:
    max_dispatches: int = 8
    max_duration_seconds: int = 180
    repeated_call_limit: int = 2


@dataclass(frozen=True)
class CycleResult:
    run_id: UUID
    status: str
    answer: str
    dispatches: int
    usage: dict[str, int]
    provider: str
    model: str
    procedure_status: str | None = None


class ActionCycle:
    """Bounded inference/action loop with evidence records and side-effect gates."""

    def __init__(
        self,
        core: StateCore,
        forge: CapabilityForge,
        *,
        limits: CycleLimits | None = None,
        operator_gate: OperatorGate | None = None,
        learner: PatternLearner | None = None,
        output_inline_bytes: int = 900,
    ) -> None:
        self.core = core
        self.forge = forge
        self.limits = limits or CycleLimits()
        self.operator_gate = operator_gate
        self.learner = learner
        self.output_inline_bytes = output_inline_bytes

    def run(
        self,
        workspace_id: UUID,
        thread_id: UUID,
        request: str,
        *,
        provider: InferenceProvider,
        instructions: str,
        root_path: Path | None = None,
        action_limit: int = 8,
        tools: tuple[GatewayTool, ...] | None = None,
    ) -> CycleResult:
        if tools is None:
            selected = self.forge.select_actions(workspace_id, request, limit=action_limit)
            tools = tuple(
                GatewayTool(
                    name=item["name"],
                    description=item["description"],
                    parameters=item["input_contract"],
                )
                for item in selected
            )
        run = self.core.start_run(thread_id, request, provider.provider_name)
        self.core.append_entry(thread_id, "operator", request)
        self.core.emit_record(
            run["id"],
            "cycle_started",
            {"provider": provider.provider_name, "model": provider.model, "actions": len(tools)},
        )
        started_at = time.monotonic()
        dispatches = 0
        usage = {"input_tokens": 0, "output_tokens": 0, "inference_calls": 0}
        repetitions: Counter[str] = Counter()
        selected_action_names = {tool.name for tool in tools}

        try:
            turn = provider.start(instructions=instructions, prompt=request, tools=tools)
            while True:
                self._add_usage(usage, turn)
                self.core.emit_record(
                    run["id"],
                    "inference_turn",
                    {"calls": len(turn.calls), "usage": turn.usage, "has_text": bool(turn.text)},
                )
                if not turn.calls:
                    answer = turn.text.strip()
                    if not answer:
                        return self._stop(
                            run["id"],
                            provider,
                            dispatches,
                            usage,
                            "provider returned neither text nor an action",
                        )
                    self.core.append_entry(thread_id, "worker", answer)
                    self.core.finish_run(
                        run["id"], status="complete", outcome=answer, usage=usage
                    )
                    procedure_status = self._learn(
                        workspace_id,
                        run["id"],
                        request,
                        dispatches,
                    )
                    return CycleResult(
                        run_id=run["id"],
                        status="complete",
                        answer=answer,
                        dispatches=dispatches,
                        usage=usage,
                        provider=provider.provider_name,
                        model=provider.model,
                        procedure_status=procedure_status,
                    )

                stop_reason = self._limit_reason(started_at, dispatches)
                if stop_reason:
                    return self._stop(run["id"], provider, dispatches, usage, stop_reason)
                outputs: list[GatewayOutput] = []
                for call in turn.calls:
                    stop_reason = self._limit_reason(started_at, dispatches)
                    if stop_reason:
                        return self._stop(run["id"], provider, dispatches, usage, stop_reason)
                    signature = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
                    repetitions[signature] += 1
                    if repetitions[signature] > self.limits.repeated_call_limit:
                        return self._stop(
                            run["id"],
                            provider,
                            dispatches,
                            usage,
                            f"repeated action blocked: {call.name}",
                        )
                    if call.name not in selected_action_names:
                        output = {"error": "action_not_selected", "action": call.name}
                        self.core.emit_record(
                            run["id"],
                            "action_rejected",
                            {"action": call.name, "reason": "not selected for this Focus Packet"},
                        )
                        outputs.append(GatewayOutput(call_id=call.call_id, content=output))
                        continue
                    action = self.forge.loaded_action(workspace_id, call.name)
                    allowed = action.risk_level is RiskLevel.READ or (
                        self.operator_gate is not None
                        and self.operator_gate(action.risk_level, call.name, call.arguments)
                    )
                    if not allowed:
                        output: Any = {"error": "operator_gate_denied", "action": call.name}
                        self.core.emit_record(
                            run["id"],
                            "operator_gate_denied",
                            {"action": call.name, "risk_level": action.risk_level.value},
                        )
                    else:
                        receipt = self.forge.invoke(
                            workspace_id,
                            call.name,
                            call.arguments,
                            context=ActionContext(
                                workspace_id=workspace_id,
                                run_id=run["id"],
                                root_path=root_path,
                            ),
                        )
                        output = self._compact_output(
                            workspace_id,
                            run["id"],
                            call.call_id,
                            receipt.output,
                        )
                        dispatches += 1
                        self.core.emit_record(
                            run["id"],
                            "action_dispatch",
                            {"action": call.name, "arguments": call.arguments},
                        )
                        self.core.emit_record(
                            run["id"],
                            "action_result",
                            {"action": call.name, "output": output},
                        )
                    outputs.append(GatewayOutput(call_id=call.call_id, content=output))
                turn = provider.continue_with_outputs(
                    turn,
                    outputs,
                    instructions=instructions,
                    tools=tools,
                )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self.core.emit_record(run["id"], "cycle_failed", {"error": message})
            self.core.finish_run(run["id"], status="failed", outcome=message, usage=usage)
            return CycleResult(
                run_id=run["id"],
                status="failed",
                answer=message,
                dispatches=dispatches,
                usage=usage,
                provider=provider.provider_name,
                model=provider.model,
            )

    def _limit_reason(self, started_at: float, dispatches: int) -> str | None:
        if dispatches >= self.limits.max_dispatches:
            return "dispatch limit reached"
        if time.monotonic() - started_at >= self.limits.max_duration_seconds:
            return "duration limit reached"
        return None

    def _compact_output(
        self,
        workspace_id: UUID,
        run_id: UUID,
        dispatch_id: str,
        output: Any,
    ) -> Any:
        serialized = json.dumps(output, default=str, ensure_ascii=False)
        if len(serialized.encode("utf-8")) <= self.output_inline_bytes:
            return output
        anchored = self.core.anchor_output(
            workspace_id,
            serialized,
            preview_bytes=self.output_inline_bytes,
            run_id=run_id,
            dispatch_id=dispatch_id,
        )
        return {
            "stored_output_id": str(anchored.id),
            "preview": anchored.preview,
            "byte_count": anchored.byte_count,
            "sha256": anchored.sha256,
        }

    def _learn(
        self,
        workspace_id: UUID,
        run_id: UUID,
        request: str,
        dispatches: int,
    ) -> str | None:
        if self.learner is None or dispatches == 0:
            return None
        try:
            receipt = self.learner.observe_success(workspace_id, run_id, request)
            self.core.emit_record(
                run_id,
                "pattern_distillation",
                {
                    "procedure_id": str(receipt.procedure_id),
                    "status": receipt.status,
                    "created": receipt.created,
                    "relevance": receipt.relevance,
                },
            )
            return receipt.status
        except Exception as error:
            self.core.emit_record(
                run_id,
                "pattern_distillation_failed",
                {"error": f"{type(error).__name__}: {error}"},
            )
            return None

    def _stop(
        self,
        run_id: UUID,
        provider: InferenceProvider,
        dispatches: int,
        usage: dict[str, int],
        reason: str,
    ) -> CycleResult:
        self.core.emit_record(run_id, "cycle_stopped", {"reason": reason})
        self.core.finish_run(run_id, status="stopped", outcome=reason, usage=usage)
        return CycleResult(
            run_id=run_id,
            status="stopped",
            answer=reason,
            dispatches=dispatches,
            usage=usage,
            provider=provider.provider_name,
            model=provider.model,
        )

    @staticmethod
    def _add_usage(total: dict[str, int], turn: GatewayTurn) -> None:
        total["inference_calls"] += 1
        total["input_tokens"] += int(turn.usage.get("input_tokens", 0))
        total["output_tokens"] += int(turn.usage.get("output_tokens", 0))
